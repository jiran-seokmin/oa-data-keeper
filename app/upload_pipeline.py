"""Runtime document upload and Gemini C/S/O classification pipeline.

The document is split into semantic sections and classified in one Gemini batch.
Only missing or malformed batch items fall back to a per-section request.  The
classifier proposes a C/S/O grade; confidence below ``REVIEW_THRESHOLD`` leaves
the section in ``pending_review`` so the access core can default-deny it.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from app import store
from app.config import classification_model, has_gemini_credentials
from app.db import DB_PATH, get_conn, init_db
from app.engine import document_grade, normalize_grade
from app.ingest import CLASSIFY_SYSTEM, KEYWORDS_PATH


MAX_UPLOAD_CHARS = 80_000
CLASSIFY_TIMEOUT_SECONDS = 45
BATCH_CLASSIFY_TIMEOUT_SECONDS = 90
REVIEW_THRESHOLD = 0.8
LOG = logging.getLogger("uvicorn.error")


class SectionLabel(BaseModel):
    """Structured classifier output; access transformations are intentionally absent."""

    grade: Literal["O", "S", "C"]
    confidence: float = Field(ge=0, le=1)
    keywords: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    summary: str
    classification_reason: str
    applied_skills: list[str] = Field(default_factory=list)


class BatchSectionLabel(SectionLabel):
    """One item in a whole-document classification response."""

    id: str


class UploadedDocument:
    def __init__(self, doc: str, doc_title: str, sections: list[dict]):
        self.doc = doc
        self.doc_title = doc_title
        self.sections = sections


def _slugify(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = re.sub(r"\.(md|txt)$", "", stem, flags=re.IGNORECASE)
    slug = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", stem).strip("_").lower()
    return slug or "uploaded_document"


def _unique_doc_id(
    base: str,
    conn: sqlite3.Connection | None = None,
    db_path: str | Path = DB_PATH,
) -> str:
    own_connection = conn is None
    conn = conn or get_conn(db_path)
    try:
        candidate = base
        index = 2
        while conn.execute("SELECT 1 FROM documents WHERE doc=?", (candidate,)).fetchone():
            candidate = f"{base}_{index}"
            index += 1
        return candidate
    finally:
        if own_connection:
            conn.close()


def _title_from_text(filename: str, content: str) -> str:
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip() or filename
    return filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def split_uploaded_document(
    filename: str,
    content: str,
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | Path = DB_PATH,
) -> UploadedDocument:
    text = content.strip()
    if not text:
        raise ValueError("빈 문서는 업로드할 수 없습니다.")
    if len(text) > MAX_UPLOAD_CHARS:
        raise ValueError(f"문서가 너무 큽니다. 최대 {MAX_UPLOAD_CHARS:,}자까지 지원합니다.")

    doc = _unique_doc_id(_slugify(filename), conn=conn, db_path=db_path)
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
        chunks.append(
            {
                "id": f"{doc}#{seq}",
                "doc": doc,
                "doc_title": doc_title,
                "seq": seq,
                "title": f"{current_heading} · 문단 {paragraph_idx}",
                "parent_title": current_heading,
                "source_section_id": f"{doc}#{seq}",
                "text": body,
            }
        )

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
        chunks.append(
            {
                "id": f"{doc}#0",
                "doc": doc,
                "doc_title": doc_title,
                "seq": 0,
                "title": "본문 · 문단 1",
                "parent_title": "본문",
                "source_section_id": f"{doc}#0",
                "text": text,
            }
        )
    return UploadedDocument(doc=doc, doc_title=doc_title, sections=chunks)


def _normalize_grade(value: object) -> str | None:
    text = str(value or "").strip().upper()
    aliases = {"OPEN": "O", "SENSITIVE": "S", "CLASSIFIED": "C"}
    candidate: object = aliases.get(text, value)
    try:
        return normalize_grade(candidate)
    except ValueError:
        return None


def _format_skill(skill: object) -> str:
    if isinstance(skill, sqlite3.Row):
        skill = dict(skill)
    if isinstance(skill, dict):
        visible = {
            str(key): value
            for key, value in skill.items()
            if key not in {"enabled", "created_at", "updated_at"} and value not in (None, "", [], {})
        }
        return json.dumps(visible, ensure_ascii=False, sort_keys=True)
    return str(skill)


def _load_enabled_skills(conn: sqlite3.Connection | None = None) -> list:
    loader = getattr(store, "load_enabled_classification_skills", None)
    if callable(loader):
        return list(loader(conn=conn))
    fallback = getattr(store, "load_skills", None)
    if callable(fallback):
        return list(fallback(enabled_only=True, conn=conn))
    return []


def _classification_system_prompt(
    conn: sqlite3.Connection | None = None,
    *,
    skills: list | None = None,
) -> str:
    config = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8")) or {}
    hints = config.get("hints") or []
    hint_lines = []
    for hint in hints:
        grade = _normalize_grade(hint.get("grade", hint.get("level")))
        if grade:
            hint_lines.append(f"- '{hint['keyword']}' -> {grade}")
    hints_text = "\n".join(hint_lines) or "- 등록된 키워드 힌트 없음"

    enabled_skills = _load_enabled_skills(conn) if skills is None else skills
    skills_text = "\n".join(f"- {_format_skill(skill)}" for skill in enabled_skills)
    if not skills_text:
        skills_text = "- 활성 분류 Skill 없음"
    return CLASSIFY_SYSTEM.format(hints=hints_text, skills=skills_text)


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
            return json.loads(cleaned[start : end + 1])
        raise


def _normalize_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def _normalize_label_payload(payload: dict) -> dict:
    """Normalize modest model-shape drift within the C/S/O response contract."""

    normalized = dict(payload)
    normalized["grade"] = _normalize_grade(normalized.get("grade"))
    if isinstance(normalized.get("confidence"), str):
        try:
            normalized["confidence"] = float(normalized["confidence"])
        except ValueError:
            normalized["confidence"] = 0.5
    normalized["keywords"] = [
        str(value).strip()
        for value in _normalize_list(normalized.get("keywords"))
        if str(value).strip()
    ]
    normalized["departments"] = [
        str(value).strip()
        for value in _normalize_list(normalized.get("departments"))
        if str(value).strip()
    ]
    normalized["summary"] = str(normalized.get("summary") or "").strip()
    normalized["classification_reason"] = str(
        normalized.get("classification_reason")
        or normalized.get("reason")
        or "모델이 제시한 키워드와 문맥을 기준으로 분류"
    ).strip()
    normalized["applied_skills"] = [
        str(value).strip()
        for value in _normalize_list(normalized.get("applied_skills"))
        if str(value).strip()
    ]
    return normalized


def _low_thinking_config(types, model: str):
    if re.match(r"gemini-[3-9]", model):
        return types.ThinkingConfig(thinking_level="low")
    if "2.5" in model and "pro" not in model:
        return types.ThinkingConfig(thinking_budget=0)
    return None


def _generate_classification(client, prompt: str, schema, *, skills: list | None = None):
    """Call Gemini with enabled user-correction skills included in the system prompt."""

    from google.genai import types

    model = classification_model()
    thinking = _low_thinking_config(types, model)
    config = types.GenerateContentConfig(
        system_instruction=_classification_system_prompt(skills=skills),
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=thinking,
    )
    try:
        return client.models.generate_content(model=model, contents=prompt, config=config)
    except Exception as exc:
        if thinking is not None and "hinking" in str(exc):
            LOG.warning("[upload] thinking config unsupported for %s; retrying without", model)
            config.thinking_config = None
            return client.models.generate_content(model=model, contents=prompt, config=config)
        raise


def _classify_with_gemini(
    section: dict,
    client=None,
    skills: list | None = None,
) -> SectionLabel:
    if client is None:
        from google import genai

        client = genai.Client()

    prompt = (
        "다음 섹션을 C/S/O 보안 등급 JSON으로만 분류하세요.\n"
        "JSON keys: grade, confidence, keywords, departments, summary, classification_reason, "
        "applied_skills.\n\n"
        f"문서: {section['doc_title']}\n섹션 제목: {section['title']}\n\n{section['text']}"
    )
    response = _generate_classification(client, prompt, SectionLabel, skills=skills)
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, SectionLabel):
        return parsed
    if isinstance(parsed, dict):
        return SectionLabel.model_validate(_normalize_label_payload(parsed))
    payload = _extract_json(getattr(response, "text", "") or "")
    return SectionLabel.model_validate(_normalize_label_payload(payload))


def _classify_with_timeout(
    section: dict,
    client=None,
    conn: sqlite3.Connection | None = None,
    skills: list | None = None,
) -> SectionLabel:
    if skills is None:
        skills = _load_enabled_skills(conn)
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_classify_with_gemini, section, client, skills)
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
            payload = json.loads(cleaned[start : end + 1])
        else:
            raise
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return value
        return [payload]
    return payload if isinstance(payload, list) else []


def _batch_items_to_labels(items: list) -> dict[str, SectionLabel]:
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
            payload = _normalize_label_payload({key: value for key, value in item.items() if key != "id"})
            labels.setdefault(section_id, SectionLabel.model_validate(payload))
        except ValidationError:
            LOG.warning("[upload] batch item invalid; falling back per-section id=%s", section_id)
    return labels


def _classify_document_with_gemini(
    sections: list[dict],
    client=None,
    skills: list | None = None,
) -> dict[str, SectionLabel]:
    if client is None:
        from google import genai

        client = genai.Client()

    blocks = "\n\n".join(
        f'<section id="{section["id"]}" title="{section["title"]}">\n'
        f'{section["text"]}\n</section>'
        for section in sections
    )
    prompt = (
        "아래 문서의 모든 <section>을 각각 C/S/O 보안 등급으로 분류해 JSON 배열로만 답하세요.\n"
        "배열의 각 항목 keys: id, grade, confidence, keywords, departments, summary, "
        "classification_reason, applied_skills.\n"
        "id는 해당 <section>의 id 속성을 그대로 복사하고 섹션 수와 항목 수를 같게 하세요.\n"
        "각 섹션은 문서 전체 맥락을 반영하되 등급은 섹션 자체 내용 기준으로 부여하세요.\n\n"
        f"문서: {sections[0]['doc_title']}\n\n{blocks}"
    )
    response = _generate_classification(client, prompt, list[BatchSectionLabel], skills=skills)
    parsed = getattr(response, "parsed", None)
    items = parsed if isinstance(parsed, list) else _extract_json_array(getattr(response, "text", "") or "")
    return _batch_items_to_labels(items)


def _classify_document_with_timeout(
    sections: list[dict],
    client=None,
    conn: sqlite3.Connection | None = None,
    skills: list | None = None,
) -> dict[str, SectionLabel]:
    if skills is None:
        skills = _load_enabled_skills(conn)
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_classify_document_with_gemini, sections, client, skills)
    try:
        return future.result(timeout=BATCH_CLASSIFY_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise RuntimeError(
            f"Gemini 문서 분류가 {BATCH_CLASSIFY_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다."
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def classify_and_store(
    filename: str,
    content: str,
    client=None,
    *,
    conn: sqlite3.Connection | None = None,
    db_path: str | Path = DB_PATH,
) -> dict:
    """Classify and persist one document.

    ``client`` bypasses credential checks so deterministic fake clients can be
    used in tests.  ``conn`` or ``db_path`` keeps those tests away from the
    workspace database; a caller-owned connection is never committed or closed.
    """

    if client is None and not has_gemini_credentials():
        raise RuntimeError("GEMINI_API_KEY 또는 GOOGLE_API_KEY가 필요합니다.")

    own_connection = conn is None
    conn = conn or get_conn(db_path)
    try:
        # A path-owned connection can safely initialize an empty test database.
        # A caller-owned connection is assumed initialized so its transaction is
        # not committed implicitly by init_db().
        if own_connection:
            init_db(conn)
        uploaded = split_uploaded_document(filename, content, conn=conn, db_path=db_path)
        classification_skills = _load_enabled_skills(conn)
        LOG.info(
            "[upload] start filename=%s doc=%s sections=%s",
            filename,
            uploaded.doc,
            len(uploaded.sections),
        )

        batch_labels: dict[str, SectionLabel] = {}
        try:
            batch_labels = _classify_document_with_timeout(
                uploaded.sections,
                client=client,
                skills=classification_skills,
            )
            LOG.info(
                "[upload] batch classified doc=%s labels=%s/%s",
                uploaded.doc,
                len(batch_labels),
                len(uploaded.sections),
            )
        except (ValidationError, json.JSONDecodeError, RuntimeError):
            LOG.exception("[upload] batch classify failed; falling back per-section doc=%s", uploaded.doc)

        classified: list[dict] = []
        for section in uploaded.sections:
            label = batch_labels.get(section["id"])
            if label is None:
                try:
                    label = _classify_with_timeout(
                        section,
                        client=client,
                        skills=classification_skills,
                    )
                except (ValidationError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"Gemini 분류 응답을 해석하지 못했습니다: {exc}") from exc
            row = dict(section)
            row.update(label.model_dump())
            row["classification_status"] = (
                "pending_review" if row["confidence"] < REVIEW_THRESHOLD else "auto_confirmed"
            )
            row["confirmed_by"] = None
            row["confirmed_at"] = None
            classified.append(row)
            LOG.info(
                "[upload] classified section=%s grade=%s confidence=%.2f status=%s",
                section["id"],
                row["grade"],
                row["confidence"],
                row["classification_status"],
            )

        store.upsert_document(
            {
                "doc": uploaded.doc,
                "doc_title": uploaded.doc_title,
                "source_path": f"runtime-upload/{uploaded.doc}",
            },
            conn=conn,
        )
        store.upsert_sections(
            [
                {key: value for key, value in row.items() if key != "applied_skills"}
                for row in classified
            ],
            conn=conn,
        )
        active_skills = classification_skills
        active_skill_lookup: dict[str, tuple[str, int | None]] = {}
        for skill in active_skills:
            item = dict(skill) if isinstance(skill, (dict, sqlite3.Row)) else {"name": str(skill)}
            display_name = str(
                item.get("name") or item.get("skill_name") or item.get("title") or item.get("id")
            ).strip()
            raw_id = item.get("id")
            skill_id = raw_id if isinstance(raw_id, int) else None
            for identifier in (
                display_name,
                str(item.get("skill_name") or ""),
                str(item.get("title") or ""),
                str(raw_id or ""),
            ):
                if identifier.strip():
                    active_skill_lookup[identifier.strip().casefold()] = (display_name, skill_id)
        for row in classified:
            store.record_classification_event(
                row["id"],
                "auto_classified",
                actor="gemini",
                new_grade=row["grade"],
                new_status=row["classification_status"],
                reason=row["classification_reason"],
                confidence=row["confidence"],
                conn=conn,
            )
            recorded_skills: set[tuple[str, int | None]] = set()
            for returned_name in row.get("applied_skills", []):
                matched = active_skill_lookup.get(returned_name.strip().casefold())
                if matched is None or matched in recorded_skills:
                    continue
                recorded_skills.add(matched)
                display_name, skill_id = matched
                store.record_classification_event(
                    row["id"],
                    "skill_applied",
                    actor="gemini",
                    new_grade=row["grade"],
                    new_status=row["classification_status"],
                    reason=f"활성 분류 Skill 적용: {display_name}",
                    confidence=row["confidence"],
                    skill_id=skill_id,
                    conn=conn,
                )

        if own_connection:
            conn.commit()
        pending_count = sum(
            1 for section in classified if section["classification_status"] == "pending_review"
        )
        return {
            "doc": uploaded.doc,
            "doc_title": uploaded.doc_title,
            "sections": len(classified),
            "document_grade": document_grade(classified),
            "pending_review": pending_count,
        }
    except Exception:
        if own_connection:
            conn.rollback()
        raise
    finally:
        if own_connection:
            conn.close()
