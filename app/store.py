"""Persistence layer for CSO classification, access and audit metadata.

The store never writes question, answer, prompt or section content to audit
logs. Source text lives only in ``sections``; log tables contain identifiers,
grades, counts and reasons.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.db import get_conn
from app.engine import (
    CLASSIFICATION_STATUSES,
    CONFIRMED_CLASSIFICATION_STATUSES,
    GRADES,
    grade_rank,
    normalize_grade,
)


_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@contextmanager
def _managed_connection(
    conn: sqlite3.Connection | None = None,
    *,
    write: bool = False,
) -> Iterator[sqlite3.Connection]:
    own = conn is None
    db = conn or get_conn()
    try:
        yield db
        if own and write:
            db.commit()
    except Exception:
        if own and write:
            db.rollback()
        raise
    finally:
        if own:
            db.close()


def _decode_list(value: object, field: str) -> list:
    if value is None:
        return []
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, list):
        raise ValueError(f"{field} must be a JSON array")
    return decoded


def _encode_list(value: object, field: str) -> str:
    return json.dumps(_decode_list(value, field), ensure_ascii=False)


def _validate_confidence(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number between 0 and 1")
    confidence = float(value)
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _validate_status(value: object) -> str:
    if not isinstance(value, str) or value not in CLASSIFICATION_STATUSES:
        raise ValueError(f"classification_status must be one of {sorted(CLASSIFICATION_STATUSES)}")
    return value


def _row_to_section(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "doc": row["doc"],
        "doc_title": row["doc_title"],
        "source_path": row["source_path"],
        "seq": row["seq"],
        "title": row["title"],
        "parent_title": row["parent_title"],
        "source_section_id": row["source_section_id"],
        "text": row["text"],
        "grade": row["grade"],
        "confidence": row["confidence"],
        "classification_status": row["classification_status"],
        "classification_reason": row["classification_reason"],
        "summary": row["summary"],
        "keywords": _decode_list(row["keywords"], "keywords"),
        "departments": _decode_list(row["departments"], "departments"),
        "confirmed_by": row["confirmed_by"],
        "confirmed_at": row["confirmed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_skill(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "instructions": row["instructions"],
        "grade": row["grade"],
        "keywords": _decode_list(row["keywords"], "keywords"),
        "examples": _decode_list(row["examples"], "examples"),
        "enabled": bool(row["enabled"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_access_log(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["section_ids"] = _decode_list(result["section_ids"], "section_ids")
    return result


_SECTION_SELECT = """
SELECT s.id, s.doc, d.doc_title, d.source_path, s.seq, s.title,
       s.parent_title, s.source_section_id, s.text, s.grade, s.confidence,
       s.classification_status, s.classification_reason, s.summary,
       s.keywords, s.departments, s.confirmed_by, s.confirmed_at,
       s.created_at, s.updated_at
FROM sections AS s
JOIN documents AS d ON d.doc = s.doc
"""


def load_sections(
    conn: sqlite3.Connection | None = None,
    *,
    classification_status: str | None = None,
) -> list[dict]:
    """Load all sections for classification/admin views."""

    clauses: list[str] = []
    params: list[object] = []
    if classification_status is not None:
        clauses.append("s.classification_status = ?")
        params.append(_validate_status(classification_status))
    sql = _SECTION_SELECT
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY s.doc, s.seq"
    with _managed_connection(conn) as db:
        return [_row_to_section(row) for row in db.execute(sql, params).fetchall()]


def get_section(section_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    with _managed_connection(conn) as db:
        row = db.execute(_SECTION_SELECT + " WHERE s.id = ?", (section_id,)).fetchone()
        return _row_to_section(row) if row else None


def sections_for_doc(doc: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    with _managed_connection(conn) as db:
        rows = db.execute(
            _SECTION_SELECT + " WHERE s.doc = ? ORDER BY s.seq", (doc,)
        ).fetchall()
        return [_row_to_section(row) for row in rows]


def load_accessible_sections(
    persona_or_grade: Mapping[str, Any] | str,
    conn: sqlite3.Connection | None = None,
    *,
    doc: str | None = None,
) -> list[dict]:
    """Read only confirmed sections at or below the user's access grade.

    Filtering happens in SQL, so denied section text is never materialized by
    this read path.
    """

    raw_grade = (
        persona_or_grade.get("access_grade")
        if isinstance(persona_or_grade, Mapping)
        else persona_or_grade
    )
    user_grade = normalize_grade(raw_grade)
    allowed_grades = GRADES[: grade_rank(user_grade) + 1]
    placeholders = ",".join("?" for _ in allowed_grades)
    sql = (
        _SECTION_SELECT
        + " WHERE s.classification_status IN ('auto_confirmed', 'user_confirmed')"
        + f" AND s.grade IN ({placeholders})"
    )
    params: list[object] = list(allowed_grades)
    if doc is not None:
        sql += " AND s.doc = ?"
        params.append(doc)
    sql += " ORDER BY s.doc, s.seq"
    with _managed_connection(conn) as db:
        return [_row_to_section(row) for row in db.execute(sql, params).fetchall()]


_DOCUMENT_SELECT = """
SELECT d.doc, d.doc_title, d.source_path, d.created_at, d.updated_at,
       CASE MAX(CASE s.grade WHEN 'O' THEN 0 WHEN 'S' THEN 1 WHEN 'C' THEN 2 END)
           WHEN 0 THEN 'O' WHEN 1 THEN 'S' WHEN 2 THEN 'C' ELSE NULL
       END AS grade,
       COUNT(s.id) AS section_count,
       SUM(CASE WHEN s.classification_status = 'pending_review' THEN 1 ELSE 0 END)
           AS pending_count,
       SUM(CASE WHEN s.classification_status IN ('auto_confirmed', 'user_confirmed')
                THEN 1 ELSE 0 END) AS confirmed_count
FROM documents AS d
LEFT JOIN sections AS s ON s.doc = d.doc
"""


def _row_to_document(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["section_count"] = int(result["section_count"] or 0)
    result["pending_count"] = int(result["pending_count"] or 0)
    result["confirmed_count"] = int(result["confirmed_count"] or 0)
    return result


def load_documents(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Load documents with a non-persisted max section ``grade``."""

    with _managed_connection(conn) as db:
        rows = db.execute(_DOCUMENT_SELECT + " GROUP BY d.doc ORDER BY d.doc").fetchall()
        return [_row_to_document(row) for row in rows]


def get_document(doc: str, conn: sqlite3.Connection | None = None) -> dict | None:
    with _managed_connection(conn) as db:
        row = db.execute(
            _DOCUMENT_SELECT + " WHERE d.doc = ? GROUP BY d.doc", (doc,)
        ).fetchone()
        return _row_to_document(row) if row else None


def classification_docs(conn: sqlite3.Connection | None = None) -> list[dict]:
    """Return document-level classification queue summaries."""

    documents = load_documents(conn)
    for document in documents:
        document["requires_review"] = document["pending_count"] > 0
    return documents


def upsert_document(
    document: Mapping[str, Any], conn: sqlite3.Connection | None = None
) -> dict:
    doc = str(document.get("doc") or "").strip()
    title = str(document.get("doc_title") or "").strip()
    if not doc or not title:
        raise ValueError("document requires non-empty doc and doc_title")
    source_path = str(document.get("source_path") or "")
    now = _now()
    with _managed_connection(conn, write=True) as db:
        db.execute(
            """INSERT INTO documents(doc, doc_title, source_path, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(doc) DO UPDATE SET
                   doc_title = excluded.doc_title,
                   source_path = excluded.source_path,
                   updated_at = excluded.updated_at""",
            (doc, title, source_path, now),
        )
        result = get_document(doc, db)
        assert result is not None
        return result


def _normalize_section(section: Mapping[str, Any]) -> dict:
    section_id = str(section.get("id") or "").strip()
    doc = str(section.get("doc") or "").strip()
    title = str(section.get("title") or "").strip()
    text = section.get("text")
    if not section_id or not doc or not title or not isinstance(text, str):
        raise ValueError("section requires id, doc, title and text")
    seq = section.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise ValueError("section seq must be a non-negative integer")

    raw_grade = section.get("grade")
    grade = normalize_grade(raw_grade) if raw_grade is not None else None
    raw_status = section.get("classification_status")
    # A classifier or reviewer must opt in to a confirmed state explicitly.
    # Merely supplying a grade is not enough to make source text readable.
    status = _validate_status(raw_status) if raw_status is not None else "pending_review"
    if status in CONFIRMED_CLASSIFICATION_STATUSES and grade is None:
        raise ValueError("confirmed classification requires a grade")

    confirmed_by = section.get("confirmed_by")
    confirmed_at = section.get("confirmed_at")
    if status == "user_confirmed":
        confirmed_by = str(confirmed_by or "").strip()
        confirmed_at = str(confirmed_at or "").strip()
        if not confirmed_by or not confirmed_at:
            raise ValueError("user_confirmed classification requires confirmed_by and confirmed_at")
    else:
        confirmed_by = None
        confirmed_at = None

    return {
        "id": section_id,
        "doc": doc,
        "seq": seq,
        "title": title,
        "parent_title": str(section.get("parent_title") or ""),
        "source_section_id": str(section.get("source_section_id") or section_id),
        "text": text,
        "grade": grade,
        "confidence": _validate_confidence(section.get("confidence")),
        "classification_status": status,
        "classification_reason": str(section.get("classification_reason") or ""),
        "summary": str(section.get("summary") or ""),
        "keywords": _encode_list(section.get("keywords"), "keywords"),
        "departments": _encode_list(section.get("departments"), "departments"),
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
    }


def upsert_sections(
    sections: Sequence[Mapping[str, Any]], conn: sqlite3.Connection | None = None
) -> list[dict]:
    normalized = [_normalize_section(section) for section in sections]
    if not normalized:
        return []
    now = _now()
    with _managed_connection(conn, write=True) as db:
        db.executemany(
            """INSERT INTO sections
               (id, doc, seq, title, parent_title, source_section_id, text, grade,
                confidence, classification_status, classification_reason, summary,
                keywords, departments, confirmed_by, confirmed_at, updated_at)
               VALUES
               (:id, :doc, :seq, :title, :parent_title, :source_section_id, :text, :grade,
                :confidence, :classification_status, :classification_reason, :summary,
                :keywords, :departments, :confirmed_by, :confirmed_at, :updated_at)
               ON CONFLICT(id) DO UPDATE SET
                   doc = excluded.doc,
                   seq = excluded.seq,
                   title = excluded.title,
                   parent_title = excluded.parent_title,
                   source_section_id = excluded.source_section_id,
                   text = excluded.text,
                   grade = excluded.grade,
                   confidence = excluded.confidence,
                   classification_status = excluded.classification_status,
                   classification_reason = excluded.classification_reason,
                   summary = excluded.summary,
                   keywords = excluded.keywords,
                   departments = excluded.departments,
                   confirmed_by = excluded.confirmed_by,
                   confirmed_at = excluded.confirmed_at,
                   updated_at = excluded.updated_at""",
            [{**section, "updated_at": now} for section in normalized],
        )
        ids = [section["id"] for section in normalized]
        return [result for section_id in ids if (result := get_section(section_id, db)) is not None]


def upsert_section(
    section: Mapping[str, Any], conn: sqlite3.Connection | None = None
) -> dict:
    return upsert_sections([section], conn)[0]


def delete_section(section_id: str, conn: sqlite3.Connection | None = None) -> bool:
    with _managed_connection(conn, write=True) as db:
        cursor = db.execute("DELETE FROM sections WHERE id = ?", (section_id,))
        return cursor.rowcount > 0


def load_personas(conn: sqlite3.Connection | None = None) -> list[dict]:
    with _managed_connection(conn) as db:
        rows = db.execute(
            """SELECT id, name, access_grade, department, channel, created_at, updated_at
               FROM personas
               ORDER BY CASE access_grade WHEN 'O' THEN 0 WHEN 'S' THEN 1 ELSE 2 END, id"""
        ).fetchall()
        return [dict(row) for row in rows]


def get_persona(persona_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    with _managed_connection(conn) as db:
        row = db.execute(
            """SELECT id, name, access_grade, department, channel, created_at, updated_at
               FROM personas WHERE id = ?""",
            (persona_id,),
        ).fetchone()
        return dict(row) if row else None


def upsert_persona(
    persona: Mapping[str, Any], conn: sqlite3.Connection | None = None
) -> dict:
    persona_id = str(persona.get("id") or "").strip()
    name = str(persona.get("name") or "").strip()
    if not persona_id or not name:
        raise ValueError("persona requires non-empty id and name")
    access_grade = normalize_grade(persona.get("access_grade"))
    channel = str(persona.get("channel") or "internal")
    if channel not in {"internal", "external"}:
        raise ValueError("channel must be internal or external")
    now = _now()
    with _managed_connection(conn, write=True) as db:
        db.execute(
            """INSERT INTO personas(id, name, access_grade, department, channel, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name = excluded.name,
                   access_grade = excluded.access_grade,
                   department = excluded.department,
                   channel = excluded.channel,
                   updated_at = excluded.updated_at""",
            (persona_id, name, access_grade, persona.get("department"), channel, now),
        )
        result = get_persona(persona_id, db)
        assert result is not None
        return result


def record_classification_event(
    section_id: str,
    action: str,
    *,
    actor: str | None = None,
    previous_grade: str | None = None,
    new_grade: str | None = None,
    previous_status: str | None = None,
    new_status: str | None = None,
    reason: str | None = None,
    confidence: float | None = None,
    skill_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Append a content-free classification audit event."""

    action = action.strip()
    if not action:
        raise ValueError("classification log action is required")
    previous_grade = normalize_grade(previous_grade) if previous_grade is not None else None
    new_grade = normalize_grade(new_grade) if new_grade is not None else None
    previous_status = _validate_status(previous_status) if previous_status is not None else None
    new_status = _validate_status(new_status) if new_status is not None else None
    confidence = _validate_confidence(confidence)

    with _managed_connection(conn, write=True) as db:
        row = db.execute("SELECT doc FROM sections WHERE id = ?", (section_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown section: {section_id}")
        cursor = db.execute(
            """INSERT INTO classification_logs
               (section_id, doc, action, actor, previous_grade, new_grade,
                previous_status, new_status, reason, confidence, skill_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                section_id,
                row["doc"],
                action,
                actor,
                previous_grade,
                new_grade,
                previous_status,
                new_status,
                reason or "",
                confidence,
                skill_id,
            ),
        )
        return int(cursor.lastrowid)


def update_section_classification(
    section_id: str,
    *,
    grade: object = _UNSET,
    confidence: object = _UNSET,
    classification_status: object = _UNSET,
    reason: object = _UNSET,
    summary: object = _UNSET,
    keywords: object = _UNSET,
    departments: object = _UNSET,
    actor: str,
    action: str = "edited",
    conn: sqlite3.Connection | None = None,
) -> dict:
    actor = actor.strip()
    if not actor:
        raise ValueError("classification update actor is required")
    with _managed_connection(conn, write=True) as db:
        current = get_section(section_id, db)
        if current is None:
            raise KeyError(f"unknown section: {section_id}")

        updated = dict(current)
        if grade is not _UNSET:
            updated["grade"] = grade
        if confidence is not _UNSET:
            updated["confidence"] = confidence
        if classification_status is not _UNSET:
            updated["classification_status"] = classification_status
        if reason is not _UNSET:
            updated["classification_reason"] = reason
        if summary is not _UNSET:
            updated["summary"] = summary
        if keywords is not _UNSET:
            updated["keywords"] = keywords
        if departments is not _UNSET:
            updated["departments"] = departments

        if updated["classification_status"] == "user_confirmed":
            updated["confirmed_by"] = actor
            updated["confirmed_at"] = _now()
        else:
            updated["confirmed_by"] = None
            updated["confirmed_at"] = None

        saved = upsert_section(updated, db)
        record_classification_event(
            section_id,
            action,
            actor=actor,
            previous_grade=current["grade"],
            new_grade=saved["grade"],
            previous_status=current["classification_status"],
            new_status=saved["classification_status"],
            reason=saved["classification_reason"],
            confidence=saved["confidence"],
            conn=db,
        )
        return saved


def confirm_classification(
    section_id: str,
    grade: str,
    reason: str,
    actor: str,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Confirm or correct a section classification and audit the change."""

    if not reason.strip():
        raise ValueError("classification confirmation reason is required")
    normalized_grade = normalize_grade(grade)
    with _managed_connection(conn, write=True) as db:
        current = get_section(section_id, db)
        if current is None:
            raise KeyError(f"unknown section: {section_id}")
        action = "corrected" if current["grade"] != normalized_grade else "confirmed"
        return update_section_classification(
            section_id,
            grade=normalized_grade,
            classification_status="user_confirmed",
            reason=reason,
            actor=actor,
            action=action,
            conn=db,
        )


def mark_classification_pending(
    section_id: str,
    reason: str,
    actor: str,
    conn: sqlite3.Connection | None = None,
) -> dict:
    if not reason.strip():
        raise ValueError("pending-review reason is required")
    return update_section_classification(
        section_id,
        classification_status="pending_review",
        reason=reason,
        actor=actor,
        action="review_requested",
        conn=conn,
    )


def load_classification_logs(
    conn: sqlite3.Connection | None = None,
    *,
    section_id: str | None = None,
    doc: str | None = None,
    limit: int = 100,
) -> list[dict]:
    limit = _validated_limit(limit)
    clauses: list[str] = []
    params: list[object] = []
    if section_id is not None:
        clauses.append("section_id = ?")
        params.append(section_id)
    if doc is not None:
        clauses.append("doc = ?")
        params.append(doc)
    sql = "SELECT * FROM classification_logs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _managed_connection(conn) as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def _validated_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")
    return limit


def create_skill(
    name: str,
    instructions: str,
    *,
    description: str = "",
    grade: str | None = None,
    keywords: Sequence[object] | None = None,
    examples: Sequence[object] | None = None,
    enabled: bool = True,
    actor: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    name = name.strip()
    instructions = instructions.strip()
    if not name or not instructions:
        raise ValueError("classification skill requires name and instructions")
    normalized_grade = normalize_grade(grade) if grade is not None else None
    with _managed_connection(conn, write=True) as db:
        cursor = db.execute(
            """INSERT INTO classification_skills
               (name, description, instructions, grade, keywords, examples, enabled, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                description,
                instructions,
                normalized_grade,
                _encode_list(keywords, "keywords"),
                _encode_list(examples, "examples"),
                1 if enabled else 0,
                actor,
            ),
        )
        result = get_skill(int(cursor.lastrowid), db)
        assert result is not None
        return result


def get_skill(skill_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
    with _managed_connection(conn) as db:
        row = db.execute("SELECT * FROM classification_skills WHERE id = ?", (skill_id,)).fetchone()
        return _row_to_skill(row) if row else None


def load_skills(
    conn: sqlite3.Connection | None = None,
    *,
    enabled_only: bool = False,
) -> list[dict]:
    sql = "SELECT * FROM classification_skills"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY name, id"
    with _managed_connection(conn) as db:
        return [_row_to_skill(row) for row in db.execute(sql).fetchall()]


def load_enabled_classification_skills(
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    return load_skills(conn, enabled_only=True)


def update_skill(
    skill_id: int,
    *,
    name: object = _UNSET,
    description: object = _UNSET,
    instructions: object = _UNSET,
    grade: object = _UNSET,
    keywords: object = _UNSET,
    examples: object = _UNSET,
    enabled: object = _UNSET,
    conn: sqlite3.Connection | None = None,
) -> dict:
    with _managed_connection(conn, write=True) as db:
        current = get_skill(skill_id, db)
        if current is None:
            raise KeyError(f"unknown classification skill: {skill_id}")
        values = {
            "name": current["name"] if name is _UNSET else str(name).strip(),
            "description": current["description"] if description is _UNSET else str(description),
            "instructions": current["instructions"] if instructions is _UNSET else str(instructions).strip(),
            "grade": current["grade"] if grade is _UNSET else (
                normalize_grade(grade) if grade is not None else None
            ),
            "keywords": _encode_list(current["keywords"] if keywords is _UNSET else keywords, "keywords"),
            "examples": _encode_list(current["examples"] if examples is _UNSET else examples, "examples"),
            "enabled": current["enabled"] if enabled is _UNSET else bool(enabled),
        }
        if not values["name"] or not values["instructions"]:
            raise ValueError("classification skill requires name and instructions")
        db.execute(
            """UPDATE classification_skills
               SET name = ?, description = ?, instructions = ?, grade = ?,
                   keywords = ?, examples = ?, enabled = ?, updated_at = ?
               WHERE id = ?""",
            (
                values["name"],
                values["description"],
                values["instructions"],
                values["grade"],
                values["keywords"],
                values["examples"],
                1 if values["enabled"] else 0,
                _now(),
                skill_id,
            ),
        )
        result = get_skill(skill_id, db)
        assert result is not None
        return result


def delete_skill(skill_id: int, conn: sqlite3.Connection | None = None) -> bool:
    with _managed_connection(conn, write=True) as db:
        cursor = db.execute("DELETE FROM classification_skills WHERE id = ?", (skill_id,))
        return cursor.rowcount > 0


def log_access(
    persona_id: str,
    action: str,
    section_ids: Sequence[str],
    blocked_count: int,
    doc: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Log access metadata without recording a question or answer."""

    action = action.strip()
    if not action:
        raise ValueError("access action is required")
    if isinstance(blocked_count, bool) or not isinstance(blocked_count, int) or blocked_count < 0:
        raise ValueError("blocked_count must be a non-negative integer")
    ids = [str(section_id) for section_id in section_ids]
    with _managed_connection(conn, write=True) as db:
        persona = get_persona(persona_id, db)
        if persona is None:
            raise KeyError(f"unknown persona: {persona_id}")
        cursor = db.execute(
            """INSERT INTO access_logs
               (persona_id, access_grade, action, doc, section_ids, allowed_count, blocked_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                persona_id,
                persona["access_grade"],
                action,
                doc,
                _encode_list(ids, "section_ids"),
                len(ids),
                blocked_count,
            ),
        )
        return int(cursor.lastrowid)


def load_access_logs(
    conn: sqlite3.Connection | None = None,
    *,
    persona_id: str | None = None,
    doc: str | None = None,
    limit: int = 100,
) -> list[dict]:
    limit = _validated_limit(limit)
    clauses: list[str] = []
    params: list[object] = []
    if persona_id is not None:
        clauses.append("persona_id = ?")
        params.append(persona_id)
    if doc is not None:
        clauses.append("doc = ?")
        params.append(doc)
    sql = "SELECT * FROM access_logs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _managed_connection(conn) as db:
        return [_row_to_access_log(row) for row in db.execute(sql, params).fetchall()]


def delete_document(doc: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """Delete a document and its sections; audit rows retain content-free metadata."""

    with _managed_connection(conn, write=True) as db:
        document = get_document(doc, db)
        if document is None:
            return None
        db.execute("DELETE FROM documents WHERE doc = ?", (doc,))
        return document
