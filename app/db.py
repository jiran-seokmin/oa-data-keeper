"""SQLite 접속·초기화 헬퍼.

DB(datakeeper.db)는 산출물이며 seed_db.py로 재생성한다 (.gitignore 대상).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "datakeeper.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"

TABLES = ("entities", "sections", "documents", "personas")


def get_conn(path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection, reset: bool = False) -> None:
    """스키마 생성. reset=True면 기존 테이블을 먼저 드롭한다."""
    if reset:
        for t in TABLES:  # entities → sections → documents 순서로 FK 안전하게 드롭
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
