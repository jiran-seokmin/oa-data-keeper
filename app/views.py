"""CSO 분류·접근 화면용 뷰 모델 조립."""

from __future__ import annotations

from app.engine import decide


def classification_section_view(section: dict) -> dict:
    return {
        "id": section["id"],
        "doc": section["doc"],
        "doc_title": section["doc_title"],
        "title": section["title"],
        "grade": section.get("grade"),
        "confidence": section.get("confidence"),
        "classification_status": section.get("classification_status"),
        "classification_reason": section.get("classification_reason", ""),
        "summary": section.get("summary", ""),
        "keywords": section.get("keywords", []),
        "departments": section.get("departments", []),
        "confirmed_by": section.get("confirmed_by"),
        "confirmed_at": section.get("confirmed_at"),
    }


def classification_section_preview(section: dict) -> dict:
    """Return source content for one explicitly requested review section."""

    return {
        "id": section["id"],
        "doc": section["doc"],
        "doc_title": section["doc_title"],
        "title": section["title"],
        "content": section["text"],
    }


def accessible_section_view(section: dict, persona: dict) -> dict | None:
    decision = decide(section, persona)
    if not decision.allowed:
        return None
    return {
        "id": section["id"],
        "doc": section["doc"],
        "doc_title": section["doc_title"],
        "title": section["title"],
        "grade": section["grade"],
        "content": section["text"],
        "summary": section.get("summary", ""),
        "access": "allowed",
        "reasons": decision.reasons,
    }
