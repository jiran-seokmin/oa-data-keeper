"""Runtime document upload and Gemini classification pipeline."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import yaml
from pydantic import BaseModel, Field, ValidationError

from app import store
from app.config import has_llm_credentials, llm_model
from app.db import get_conn
from app.ingest import CLASSIFY_SYSTEM, KEYWORDS_PATH, assign_placeholders


MAX_UPLOAD_CHARS = 80_000


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


def _classify_with_gemini(section: dict, client=None) -> SectionLabel:
    if client is None:
        from google import genai
        client = genai.Client()
    from google.genai import types

    prompt = (
        "다음 섹션을 보안 등급 JSON으로만 분류하세요.\n"
        "JSON keys: security_level, confidence, keywords, departments, summary_generalized, entities.\n\n"
        f"문서: {section['doc_title']}\n섹션 제목: {section['title']}\n\n{section['text']}"
    )
    response = client.models.generate_content(
        model=llm_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_classification_system_prompt(),
            response_mime_type="application/json",
        ),
    )
    payload = _extract_json(getattr(response, "text", "") or "")
    return SectionLabel.model_validate(payload)


def classify_and_store(filename: str, content: str, client=None) -> dict:
    if not has_llm_credentials() and client is None:
        raise RuntimeError("GEMINI_API_KEY 또는 GOOGLE_API_KEY가 필요합니다.")

    uploaded = split_uploaded_document(filename, content)
    classified: list[dict] = []
    for section in uploaded.sections:
        try:
            label = _classify_with_gemini(section, client=client)
        except (ValidationError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Gemini 분류 응답을 해석하지 못했습니다: {exc}") from exc
        row = dict(section)
        row.update(label.model_dump())
        row["entities"] = [dict(e) for e in row["entities"] if e.get("text") and e["text"] in row["text"]]
        row["needs_review"] = row["confidence"] < 0.8 or row["security_level"] >= 3
        classified.append(row)

    existing = store.load_sections()
    assign_placeholders(existing + classified)
    _insert_uploaded(uploaded, classified)
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
