"""Lossless legacy D0-D4 database migration test."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_conn, migrate_legacy_db, schema_state


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def _create_legacy_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE documents (
                doc TEXT PRIMARY KEY, doc_title TEXT NOT NULL, source_path TEXT NOT NULL
            );
            CREATE TABLE sections (
                id TEXT PRIMARY KEY, doc TEXT NOT NULL, seq INTEGER NOT NULL,
                title TEXT NOT NULL, parent_title TEXT NOT NULL,
                source_section_id TEXT NOT NULL, text TEXT NOT NULL,
                security_level INTEGER, confidence REAL, needs_review INTEGER,
                keywords TEXT, departments TEXT, summary_generalized TEXT
            );
            CREATE TABLE personas (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, clearance INTEGER NOT NULL,
                department TEXT, channel TEXT
            );
            CREATE TABLE entities (
                id INTEGER PRIMARY KEY, section_id TEXT, text TEXT
            );
            INSERT INTO documents VALUES ('legacy', '기존 문서', 'legacy.md');
            """
        )
        conn.executemany(
            """INSERT INTO sections
               VALUES (?, 'legacy', ?, ?, '', ?, ?, ?, 0.9, ?, '[]', '[]', '')""",
            [
                (f"legacy#{level}", level, f"섹션 {level}", f"legacy#{level}",
                 f"기존 원문 {level}", level, 1 if level == 3 else 0)
                for level in range(5)
            ],
        )
        conn.executemany(
            "INSERT INTO personas VALUES (?, ?, ?, NULL, 'internal')",
            [(f"user-{level}", f"사용자 {level}", level) for level in range(5)],
        )
        conn.execute("INSERT INTO entities VALUES (1, 'legacy#4', '기존 엔티티')")
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "legacy.db"
        _create_legacy_database(db_path)
        result = migrate_legacy_db(db_path)
        backup_path = Path(result["backup_path"])

        check("마이그레이션 전 자동 백업", backup_path.exists())
        old = get_conn(backup_path)
        current = get_conn(db_path)
        try:
            check("백업은 기존 스키마 유지", schema_state(old) == "legacy")
            check("대상은 CSO 스키마", schema_state(current) == "current")
            rows = current.execute(
                "SELECT id, grade, classification_status FROM sections ORDER BY seq"
            ).fetchall()
            check("D0→O, D1~D3→S, D4→C", [row["grade"] for row in rows] == [
                "O", "S", "S", "S", "C"
            ])
            check("기존 검수 플래그는 pending_review", rows[3]["classification_status"] == "pending_review")
            check("문서·섹션·사용자 보존", (
                result["documents"], result["sections"], result["personas"]
            ) == (1, 5, 5))
            check("사용자 접근 등급도 O/S/C로 변환", [
                row[0] for row in current.execute(
                    "SELECT access_grade FROM personas ORDER BY id"
                ).fetchall()
            ] == ["O", "S", "S", "S", "C"])
            check("기존 엔티티 구조 제거", not current.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entities'"
            ).fetchone())
            check("섹션별 변환 이력", current.execute(
                "SELECT COUNT(*) FROM classification_logs WHERE action='legacy_migrated'"
            ).fetchone()[0] == 5)
            check("외래키 무결성", current.execute("PRAGMA foreign_key_check").fetchall() == [])
        finally:
            old.close()
            current.close()

    print("\n레거시 DB 마이그레이션 테스트 통과 ✅")


if __name__ == "__main__":
    main()
