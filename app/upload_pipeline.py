"""Runtime document upload and Gemini classification pipeline.

분류는 문서 전체를 Gemini에 1회 호출(배치)로 보내 모든 문단 라벨을 한 번에 받는다
(문단별 순차 호출은 문단 수에 비례해 느려져 FE 타임아웃을 유발했다). 배치 응답에서
누락·불량인 섹션만 기존 문단별 호출로 폴백한다.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass

import yaml
from pydantic import BaseModel, Field, ValidationError

from app import store
from app.config import has_llm_credentials, llm_model
from app.db import get_conn
from app.ingest import CLASSIFY_SYSTEM, KEYWORDS_PATH, assign_placeholders


MAX_UPLOAD_CHARS = 80_000
CLASSIFY_TIMEOUT_SECONDS = 45
BATCH_CLASSIFY_TIMEOUT_SECONDS = 90
LOG = logging.getLogger("uvicorn.error")


class EntityLabel(BaseModel):
    text: str
    type: str = Field(description="고객사/인물/금액/수치/조건/코드네임/경쟁사 등")


class SectionLabel(BaseModel):
    security_level: int = Field(ge=0, le=4)
    confidence: float = Field(ge=0, le=1)
    keywords: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    summary_generalized: str
    entities: list[EntityLabel] = Field(default_factory=list)


class BatchSectionLabel(SectionLabel):
    """문서 전체 1회 분류 응답의 항목 — 어느 섹션의 라벨인지 id로 매칭한다."""

    id: str


@dataclass
class UploadedDocument:
    doc: str
    doc_title: str
    sections: list[dict]


def _slugify(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = re.sub(r"\.(md|txt)$", "", stem, flags=re.IGNORECASE)
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", stem).strip("_").lower()
    return slug or "uploaded_document"


def _unique_doc_id(base: str) -> str:
    conn = get_conn()
    try:
        candidate = base
        index = 2
        while conn.execute("SELECT 1 FROM documents WHERE doc=?", (candidate,)).fetchone():
            candidate = f"{base}_{index}"
            index += 1
        return candidate
    finally:
        conn.close()


def _title_from_text(filename: str, content: str) -> str:
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip() or filename
    return filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def split_uploaded_document(filename: str, content: str) -> UploadedDocument:
    text = content.strip()
    if not text:
        raise ValueError("빈 문서는 업로드할 수 없습니다.")
    if len(text) > MAX_UPLOAD_CHARS:
        raise ValueError(f"문서가 너무 큽니다. 최대 {MAX_UPLOAD_CHARS:,}자까지 지원합니다.")

    doc = _unique_doc_id(_slugify(filename))
    doc_title = _title_from_text(filename, text)
    chunks: list[dict] = []
    current_heading = "본문"
    paragraph_idx = 0
    paragraph_lines: list[str] = []

    def flush() -> None:
        nonlocal paragraph_lines, paragraph_idx
        body = "\n".join(line.strip() for line in paragraph_lines).strip()
        paragraph_lines = []
        if not body:
            return
        seq = len(chunks)
        paragraph_idx += 1
        chunks.append({
            "id": f"{doc}#{seq}",
            "doc": doc,
            "doc_title": doc_title,
            "seq": seq,
            "title": f"{current_heading} · 문단 {paragraph_idx}",
            "parent_title": current_heading,
            "source_section_id": f"{doc}#{seq}",
            "text": body,
        })

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("# ") and not line.startswith("## "):
            continue
        if line.startswith("## "):
            flush()
            current_heading = line[3:].strip() or "본문"
            paragraph_idx = 0
            continue
        if not line.strip():
            flush()
            continue
        paragraph_lines.append(line)
    flush()

    if not chunks:
        chunks.append({
            "id": f"{doc}#0",
            "doc": doc,
            "doc_title": doc_title,
            "seq": 0,
            "title": "본문 · 문단 1",
            "parent_title": "본문",
            "source_section_id": f"{doc}#0",
            "text": text,
        })
    return UploadedDocument(doc=doc, doc_title=doc_title, sections=chunks)


def _classification_system_prompt() -> str:
    hints = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8"))["hints"]
    hints_text = "\n".join(f"- '{h['keyword']}' → D{h['level']}" for h in hints)
    return CLASSIFY_SYSTEM.format(hints=hints_text)


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _normalize_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def _infer_entity_type(text: str) -> str:
    if re.search(r"\d", text) and re.search(r"(억|만|원|퍼센트|%|년|월|일|분기|개월|명|개|건)", text):
        if re.search(r"(억|만|원)", text):
            return "금액"
        if re.search(r"(년|월|일|분기|개월)", text):
            return "일정"
        return "수치"
    if re.search(r"(프로젝트|코드|Project)", text, re.IGNORECASE):
        return "코드네임"
    return "민감정보"


def _normalize_label_payload(payload: dict) -> dict:
    """Tolerate common Gemini shape drift while preserving strict DB schema.

    Gemini sometimes returns `entities` as `["DataKeeper", "35퍼센트"]` even
    when prompted for `{text,type}` objects. Convert those into typed entity
    dictionaries so the pipeline remains usable and auditable.
    """
    normalized = dict(payload)
    if isinstance(normalized.get("security_level"), str):
        match = re.search(r"[0-4]", normalized["security_level"])
        if match:
            normalized["security_level"] = int(match.group(0))
    if isinstance(normalized.get("confidence"), str):
        try:
            normalized["confidence"] = float(normalized["confidence"])
        except ValueError:
            normalized["confidence"] = 0.5
    normalized["keywords"] = [str(v) for v in _normalize_list(normalized.get("keywords")) if str(v).strip()]
    normalized["departments"] = [str(v) for v in _normalize_list(normalized.get("departments")) if str(v).strip()]

    entities = []
    for item in _normalize_list(normalized.get("entities")):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("value") or "").strip()
            if not text:
                continue
            entity_type = str(item.get("type") or item.get("label") or _infer_entity_type(text)).strip()
            entities.append({"text": text, "type": entity_type or "민감정보"})
        elif isinstance(item, str):
            text = item.strip()
            if text:
                entities.append({"text": text, "type": _infer_entity_type(text)})
    normalized["entities"] = entities
    return normalized


def _low_thinking_config(types, model: str):
    """분류는 정형 작업이라 깊은 사고가 불필요 — 사고 토큰이 지연의 2/3를 차지한다.

    실측(gemini-3.5-flash, 15문단 배치): 기본 31.9s → low 9.5s, 라벨 15/15 동일 수준.
    세대별 API가 다르다: gemini-3.x는 thinking_level, 2.5 계열은 thinking_budget.
    """
    if re.match(r"gemini-[3-9]", model):
        return types.ThinkingConfig(thinking_level="low")
    if "2.5" in model and "pro" not in model:
        return types.ThinkingConfig(thinking_budget=0)
    return None


def _generate_classification(client, prompt: str, schema):
    """분류 프롬프트를 저사고 설정으로 호출. 사고 설정 미지원 모델이면 빼고 1회 재시도."""
    from google.genai import types

    thinking = _low_thinking_config(types, llm_model())
    config = types.GenerateContentConfig(
        system_instruction=_classification_system_prompt(),
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=thinking,
    )
    try:
        return client.models.generate_content(model=llm_model(), contents=prompt, config=config)
    except Exception as exc:
        if thinking is not None and "hinking" in str(exc):
            LOG.warning("[upload] thinking config unsupported for %s — retrying without", llm_model())
            config.thinking_config = None
            return client.models.generate_content(model=llm_model(), contents=prompt, config=config)
        raise


def _classify_with_gemini(section: dict, client=None) -> SectionLabel:
    if client is None:
        from google import genai
        client = genai.Client()

    prompt = (
        "다음 섹션을 보안 등급 JSON으로만 분류하세요.\n"
        "JSON keys: security_level, confidence, keywords, departments, summary_generalized, entities.\n"
        "entities는 반드시 객체 배열입니다. 예: [{\"text\":\"한빛전자\",\"type\":\"고객사\"}].\n\n"
        f"문서: {section['doc_title']}\n섹션 제목: {section['title']}\n\n{section['text']}"
    )
    response = _generate_classification(client, prompt, SectionLabel)
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, SectionLabel):
        return parsed
    if isinstance(parsed, dict):
        return SectionLabel.model_validate(_normalize_label_payload(parsed))
    payload = _extract_json(getattr(response, "text", "") or "")
    return SectionLabel.model_validate(_normalize_label_payload(payload))


def _classify_with_timeout(section: dict, client=None) -> SectionLabel:
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_classify_with_gemini, section, client)
    try:
        return future.result(timeout=CLASSIFY_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise RuntimeError(
            f"Gemini 분류가 {CLASSIFY_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다. "
            "문서를 더 작은 단위로 나누거나 잠시 후 다시 시도해주세요."
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _extract_json_array(text: str) -> list:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start >= 0 and end > start:
            payload = json.loads(cleaned[start:end + 1])
        else:
            raise
    if isinstance(payload, dict):  # {"sections": [...]} 형태 관용 처리
        for value in payload.values():
            if isinstance(value, list):
                return value
        return [payload]
    return payload if isinstance(payload, list) else []


def _batch_items_to_labels(items: list) -> dict[str, SectionLabel]:
    """배치 응답 항목들을 섹션 id → SectionLabel 매핑으로 정규화. 불량 항목은 건너뛴다."""
    labels: dict[str, SectionLabel] = {}
    for item in items:
        if isinstance(item, BatchSectionLabel):
            labels.setdefault(item.id, SectionLabel.model_validate(item.model_dump(exclude={"id"})))
            continue
        if isinstance(item, BaseModel):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("id") or "").strip()
        if not section_id:
            continue
        try:
            payload = _normalize_label_payload({k: v for k, v in item.items() if k != "id"})
            labels.setdefault(section_id, SectionLabel.model_validate(payload))
        except ValidationError:
            LOG.warning("[upload] batch item invalid — fallback to per-section id=%s", section_id)
    return labels


def _classify_document_with_gemini(sections: list[dict], client=None) -> dict[str, SectionLabel]:
    """문서 전체를 1회 호출로 분류해 섹션 id → 라벨 매핑을 반환한다."""
    if client is None:
        from google import genai
        client = genai.Client()

    blocks = "\n\n".join(
        f'<section id="{s["id"]}" title="{s["title"]}">\n{s["text"]}\n</section>'
        for s in sections
    )
    prompt = (
        "아래 문서의 모든 <section>을 각각 보안 등급 JSON으로 분류해 JSON 배열로만 답하세요.\n"
        "배열의 각 항목 keys: id, security_level, confidence, keywords, departments, "
        "summary_generalized, entities.\n"
        "id는 해당 <section>의 id 속성을 그대로 복사합니다. 섹션 수와 항목 수가 같아야 합니다.\n"
        "entities는 반드시 객체 배열입니다. 예: [{\"text\":\"한빛전자\",\"type\":\"고객사\"}].\n"
        "각 섹션은 문서 전체 맥락을 반영해 판단하되, 등급은 섹션 자체 내용 기준으로 부여하세요.\n\n"
        f"문서: {sections[0]['doc_title']}\n\n{blocks}"
    )
    response = _generate_classification(client, prompt, list[BatchSectionLabel])
    parsed = getattr(response, "parsed", None)
    items = parsed if isinstance(parsed, list) else _extract_json_array(getattr(response, "text", "") or "")
    return _batch_items_to_labels(items)


def _classify_document_with_timeout(sections: list[dict], client=None) -> dict[str, SectionLabel]:
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_classify_document_with_gemini, sections, client)
    try:
        return future.result(timeout=BATCH_CLASSIFY_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise RuntimeError(
            f"Gemini 문서 분류가 {BATCH_CLASSIFY_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다."
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def classify_and_store(filename: str, content: str, client=None) -> dict:
    if not has_llm_credentials() and client is None:
        raise RuntimeError("GEMINI_API_KEY 또는 GOOGLE_API_KEY가 필요합니다.")

    uploaded = split_uploaded_document(filename, content)
    LOG.info(
        "[upload] start filename=%s doc=%s sections=%s",
        filename,
        uploaded.doc,
        len(uploaded.sections),
    )

    # 1차: 문서 전체 1회 호출 배치 분류 (실패해도 문단별 폴백이 있으므로 치명적이지 않다)
    batch_labels: dict[str, SectionLabel] = {}
    try:
        batch_labels = _classify_document_with_timeout(uploaded.sections, client=client)
        LOG.info(
            "[upload] batch classified doc=%s labels=%s/%s",
            uploaded.doc,
            len(batch_labels),
            len(uploaded.sections),
        )
    except (ValidationError, json.JSONDecodeError, RuntimeError):
        LOG.exception("[upload] batch classify failed — falling back per-section doc=%s", uploaded.doc)

    classified: list[dict] = []
    for section in uploaded.sections:
        label = batch_labels.get(section["id"])
        if label is None:
            # 2차: 배치 응답에 없거나 불량인 섹션만 문단별 호출로 폴백
            try:
                LOG.info(
                    "[upload] fallback classify section=%s title=%s chars=%s",
                    section["id"],
                    section["title"],
                    len(section["text"]),
                )
                label = _classify_with_timeout(section, client=client)
            except (ValidationError, json.JSONDecodeError) as exc:
                LOG.exception("[upload] invalid Gemini response section=%s", section["id"])
                raise RuntimeError(f"Gemini 분류 응답을 해석하지 못했습니다: {exc}") from exc
            except RuntimeError:
                LOG.exception("[upload] classify failed section=%s", section["id"])
                raise
        row = dict(section)
        row.update(label.model_dump())
        row["entities"] = [dict(e) for e in row["entities"] if e.get("text") and e["text"] in row["text"]]
        row["needs_review"] = row["confidence"] < 0.8 or row["security_level"] >= 3
        classified.append(row)
        LOG.info(
            "[upload] classified section=%s D%s confidence=%.2f entities=%s",
            section["id"],
            row["security_level"],
            row["confidence"],
            len(row["entities"]),
        )

    existing = store.load_sections()
    assign_placeholders(existing + classified)
    _insert_uploaded(uploaded, classified)
    LOG.info("[upload] stored doc=%s sections=%s", uploaded.doc, len(classified))
    return {
        "doc": uploaded.doc,
        "doc_title": uploaded.doc_title,
        "sections": len(classified),
        "max_d": max((s["security_level"] for s in classified), default=4),
        "needs_review": sum(1 for s in classified if s["needs_review"]),
    }


def _insert_uploaded(uploaded: UploadedDocument, sections: list[dict]) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO documents(doc, doc_title, source_path) VALUES (?,?,?)",
            (uploaded.doc, uploaded.doc_title, f"runtime-upload/{uploaded.doc}"),
        )
        conn.executemany(
            """INSERT INTO sections
               (id, doc, seq, title, parent_title, source_section_id, text, security_level, confidence,
                needs_review, keywords, departments, summary_generalized)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    s["id"], s["doc"], s["seq"], s["title"], s["parent_title"],
                    s["source_section_id"], s["text"],
                    s["security_level"], s["confidence"], 1 if s["needs_review"] else 0,
                    json.dumps(s["keywords"], ensure_ascii=False),
                    json.dumps(s["departments"], ensure_ascii=False),
                    s["summary_generalized"],
                )
                for s in sections
            ],
        )
        conn.executemany(
            "INSERT INTO entities(section_id, seq, text, placeholder, type) VALUES (?,?,?,?,?)",
            [
                (s["id"], i, e["text"], e["placeholder"], e.get("type"))
                for s in sections
                for i, e in enumerate(s["entities"])
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
