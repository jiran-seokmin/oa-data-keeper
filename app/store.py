"""DB 접근 계층.

반환되는 섹션 dict는 기존 data/sections.json 항목과 **동일한 키 스키마**를 갖는다.
그래야 app/engine.py의 decide()와 app/pipeline.py의 render_block()을 수정 없이 재사용한다.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db import DB_PATH, get_conn


def _entities_for(conn: sqlite3.Connection, section_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT text, placeholder, type FROM entities WHERE section_id=? ORDER BY seq",
        (section_id,),
    ).fetchall()
    return [{"text": r["text"], "placeholder": r["placeholder"], "type": r["type"]} for r in rows]


def _row_to_section(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "doc": r["doc"],
        "doc_title": r["doc_title"],
        "title": r["title"],
        "parent_title": r["parent_title"],
        "source_section_id": r["source_section_id"],
        "text": r["text"],
        "security_level": r["security_level"],
        "confidence": r["confidence"],
        "needs_review": bool(r["needs_review"]),
        "keywords": json.loads(r["keywords"]),
        "departments": json.loads(r["departments"]),
        "summary_generalized": r["summary_generalized"],
        "entities": _entities_for(conn, r["id"]),
    }


_SECTION_SELECT = (
    "SELECT s.*, d.doc_title AS doc_title "
    "FROM sections s JOIN documents d ON s.doc = d.doc"
)


def load_sections(conn: sqlite3.Connection | None = None, external_only: bool = False) -> list[dict]:
    """전체 섹션을 sections.json 스키마 dict 리스트로 반환.

    external_only=True면 외부 채널용 코스 메타데이터 사전 필터(D0만)를 적용한다.
    (정밀 판정은 항상 engine.decide()가 담당 — 이건 인덱스 진입 전 코스 컷.)
    """
    own = conn is None
    conn = conn or get_conn()
    try:
        sql = _SECTION_SELECT
        if external_only:
            sql += " WHERE s.security_level = 0"
        sql += " ORDER BY s.doc, s.seq"
        return [_row_to_section(conn, r) for r in conn.execute(sql).fetchall()]
    finally:
        if own:
            conn.close()


def sections_for_doc(doc: str, conn: sqlite3.Connection | None = None) -> list[dict]:
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            _SECTION_SELECT + " WHERE s.doc = ? ORDER BY s.seq", (doc,)
        ).fetchall()
        return [_row_to_section(conn, r) for r in rows]
    finally:
        if own:
            conn.close()


def load_personas(conn: sqlite3.Connection | None = None) -> list[dict]:
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, clearance, department, channel FROM personas ORDER BY clearance"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def load_documents(conn: sqlite3.Connection | None = None) -> list[dict]:
    own = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT doc, doc_title, source_path FROM documents ORDER BY doc"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_persona(persona_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    own = conn is None
    conn = conn or get_conn()
    try:
        r = conn.execute(
            "SELECT id, name, clearance, department, channel FROM personas WHERE id=?",
            (persona_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        if own:
            conn.close()
