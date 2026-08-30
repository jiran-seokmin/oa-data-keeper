"""Classification confirmation and feedback-to-skill orchestration.

This module keeps the human review workflow transactional: a confirmed grade,
its content-free audit event, and the reusable classifier skill are committed
together.  Section source text is deliberately excluded from skills and logs.
"""

from __future__ import annotations

import sqlite3

from app import store
from app.db import get_conn
from app.engine import normalize_grade


def _feedback_skill_name(section_id: str) -> str:
    return f"feedback:{section_id}"


def _skill_payload(section: dict, grade: str, reason: str) -> dict:
    keywords = [str(value) for value in section.get("keywords", []) if str(value).strip()]
    keyword_text = ", ".join(keywords) if keywords else "등록된 키워드 없음"
    return {
        "name": _feedback_skill_name(section["id"]),
        "description": f"{section['doc_title']} / {section['title']} 사용자 분류 피드백",
        "instructions": (
            f"다음 분류 피드백을 유사 문맥에 적용하세요: 등급 {grade}; "
            f"키워드 {keyword_text}; 판단 근거 {reason.strip()}"
        ),
        "grade": grade,
        "keywords": keywords,
        "examples": [
            {
                "document": section["doc"],
                "section_title": section["title"],
                "grade": grade,
                "reason": reason.strip(),
            }
        ],
    }


def confirm_and_learn(
    section_id: str,
    grade: str,
    reason: str,
    actor: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Confirm/edit a grade and upsert its reusable classification skill.

    When no connection is supplied, the operation owns a transaction.  Callers
    with an existing connection remain responsible for commit/rollback.
    """

    normalized_grade = normalize_grade(grade)
    clean_reason = reason.strip()
    clean_actor = actor.strip()
    if not clean_reason:
        raise ValueError("classification confirmation reason is required")
    if not clean_actor:
        raise ValueError("classification confirmation actor is required")

    own_connection = conn is None
    db = conn or get_conn()
    try:
        current = store.get_section(section_id, db)
        if current is None:
            raise KeyError(f"unknown section: {section_id}")

        section = store.confirm_classification(
            section_id,
            normalized_grade,
            clean_reason,
            clean_actor,
            conn=db,
        )
        payload = _skill_payload(section, normalized_grade, clean_reason)
        existing = next(
            (
                skill
                for skill in store.load_skills(db)
                if skill["name"] == payload["name"]
            ),
            None,
        )
        if existing is None:
            skill = store.create_skill(
                payload["name"],
                payload["instructions"],
                description=payload["description"],
                grade=payload["grade"],
                keywords=payload["keywords"],
                examples=payload["examples"],
                actor=clean_actor,
                conn=db,
            )
            skill_action = "skill_created"
        else:
            skill = store.update_skill(
                existing["id"],
                description=payload["description"],
                instructions=payload["instructions"],
                grade=payload["grade"],
                keywords=payload["keywords"],
                examples=payload["examples"],
                enabled=True,
                conn=db,
            )
            skill_action = "skill_updated"

        store.record_classification_event(
            section_id,
            skill_action,
            actor=clean_actor,
            previous_grade=current["grade"],
            new_grade=section["grade"],
            previous_status=current["classification_status"],
            new_status=section["classification_status"],
            reason=clean_reason,
            confidence=section["confidence"],
            skill_id=skill["id"],
            conn=db,
        )
        if own_connection:
            db.commit()
        return {"section": section, "skill": skill, "skill_action": skill_action}
    except Exception:
        if own_connection:
            db.rollback()
        raise
    finally:
        if own_connection:
            db.close()
