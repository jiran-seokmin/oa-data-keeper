"""Runtime Skill, browser chat generation and audit-log cleanup test."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as db_module, store
from app.db import (
    CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX,
    CLEAR_CHAT_SESSION_GENERATION_PREFIX,
    clear_runtime_data,
    get_chat_session_generation,
    get_conn,
    init_db,
    runtime_data_counts,
)


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def _rows(conn, table: str) -> list[tuple]:
    return [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')]


def _seed_runtime_data(db_path: Path) -> tuple[dict[str, list[tuple]], str]:
    conn = get_conn(db_path)
    try:
        init_db(conn)
        store.upsert_document(
            {"doc": "keep", "doc_title": "보존 문서", "source_path": "keep.md"},
            conn,
        )
        store.upsert_section(
            {
                "id": "keep#0",
                "doc": "keep",
                "seq": 0,
                "title": "보존 섹션",
                "text": "삭제되면 안 되는 원문",
                "grade": "S",
                "confidence": 0.95,
                "classification_status": "auto_confirmed",
                "classification_reason": "보존 확인",
                "summary": "보존 요약",
                "keywords": ["보존"],
                "departments": ["보안팀"],
            },
            conn,
        )
        store.upsert_persona(
            {"id": "reviewer", "name": "검토자", "access_grade": "C"},
            conn,
        )
        skill = store.create_skill(
            "삭제할 Skill",
            "다음 자동 분류에만 사용하는 지침",
            grade="S",
            actor="test",
            conn=conn,
        )
        store.record_classification_event(
            "keep#0",
            "skill_created",
            actor="test",
            new_grade="S",
            new_status="auto_confirmed",
            reason="정리 테스트",
            confidence=0.95,
            skill_id=skill["id"],
            conn=conn,
        )
        store.log_access(
            "reviewer", "chat", ["keep#0"], 0, doc="keep", conn=conn
        )
        conn.commit()
        preserved = {
            table: _rows(conn, table) for table in ("documents", "sections", "personas")
        }
        generation = get_chat_session_generation(conn)
        return preserved, generation
    finally:
        conn.close()


def main() -> None:
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "clear-runtime-test.db"
        preserved_before, generation_before = _seed_runtime_data(db_path)
        check("최초 세대는 기존 채팅 보존용 기준값", (
            generation_before.startswith(CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX)
        ))

        counts = runtime_data_counts(db_path)
        check("삭제 전 대상 건수 보고", all(counts[table] == 1 for table in (
            "classification_skills", "classification_logs", "access_logs"
        )))

        conn = get_conn(db_path)
        try:
            conn.execute(
                """CREATE TRIGGER reject_log_delete
                   BEFORE DELETE ON classification_logs
                   BEGIN
                       SELECT RAISE(ABORT, 'forced rollback');
                   END"""
            )
            conn.commit()
        finally:
            conn.close()
        rollback_backup_path = Path(directory) / "forced-rollback-backup.db"
        try:
            clear_runtime_data(db_path, backup=rollback_backup_path)
        except Exception as exc:
            check("중간 실패가 호출자에게 전달", "forced rollback" in str(exc))
            check("실패 메시지에 보존 백업 경로 표시", (
                str(rollback_backup_path.resolve()) in str(exc)
            ))
            check("실패 원인 예외 체인 보존", isinstance(exc.__cause__, sqlite3.Error))
        else:
            raise AssertionError("forced rollback was not raised")
        check("중간 실패 시 복구용 백업 보존", rollback_backup_path.exists())
        rollback_backup = get_conn(rollback_backup_path)
        try:
            check("중간 실패 백업에 삭제 전 데이터 보존", all(
                rollback_backup.execute(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).fetchone()[0] == 1
                for table in ("classification_skills", "classification_logs", "access_logs")
            ))
        finally:
            rollback_backup.close()
        check("중간 실패 시 전체 롤백", all(
            runtime_data_counts(db_path)[table] == 1
            for table in ("classification_skills", "classification_logs", "access_logs")
        ))

        conn = get_conn(db_path)
        try:
            conn.execute("DROP TRIGGER reject_log_delete")
            conn.commit()
        finally:
            conn.close()

        conn = get_conn(db_path)
        try:
            conn.execute(
                """CREATE TRIGGER mutate_preserved_section
                   AFTER DELETE ON access_logs
                   BEGIN
                       UPDATE sections SET text = 'unexpected mutation' WHERE id = 'keep#0';
                   END"""
            )
            conn.commit()
        finally:
            conn.close()
        try:
            clear_runtime_data(db_path, backup=False)
        except RuntimeError as exc:
            check("보존 데이터 trigger 부작용 감지", "unexpected database side effects" in str(exc))
        else:
            raise AssertionError("preserved-data side effect was not detected")
        conn = get_conn(db_path)
        try:
            check("부작용 감지 시 원문과 대상 삭제 롤백", (
                conn.execute("SELECT text FROM sections WHERE id = 'keep#0'").fetchone()[0]
                == "삭제되면 안 되는 원문"
                and all(
                    conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 1
                    for table in ("classification_skills", "classification_logs", "access_logs")
                )
            ))
            conn.execute("DROP TRIGGER mutate_preserved_section")
            conn.commit()
        finally:
            conn.close()

        result = clear_runtime_data(db_path)
        backup_path = Path(result["backup_path"])
        check("삭제 전 자동 백업", backup_path.exists())
        check("세 대상만 정확히 삭제", result["deleted"] == {
            "access_logs": 1,
            "classification_logs": 1,
            "classification_skills": 1,
        })

        conn = get_conn(db_path)
        backup = get_conn(backup_path)
        try:
            check("Skill·분류·접근 로그 0건", all(
                conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
                for table in ("classification_skills", "classification_logs", "access_logs")
            ))
            check("문서·섹션·페르소나 행 보존", all(
                _rows(conn, table) == preserved_before[table]
                for table in ("documents", "sections", "personas")
            ))
            check("채팅 세션 세대 교체", (
                get_chat_session_generation(conn) != generation_before
                and get_chat_session_generation(conn) == result["chat_session_generation"]
                and result["chat_session_generation"].startswith(
                    CLEAR_CHAT_SESSION_GENERATION_PREFIX
                )
            ))
            check("외래 키 무결성", conn.execute("PRAGMA foreign_key_check").fetchall() == [])
            check("백업에 삭제 전 데이터 보존", all(
                backup.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 1
                for table in ("classification_skills", "classification_logs", "access_logs")
            ))
            check("백업의 기존 세션 세대 보존", (
                get_chat_session_generation(backup) == generation_before
            ))
        finally:
            backup.close()
            conn.close()

        second = clear_runtime_data(db_path, backup=False)
        check("빈 대상에서 반복 실행 가능", all(
            count == 0 for count in second["deleted"].values()
        ))
        check("반복 실행도 채팅 세션 재무효화", (
            second["chat_session_generation"] != result["chat_session_generation"]
        ))

        version_two_path = Path(directory) / "version-two-runtime-test.db"
        _seed_runtime_data(version_two_path)
        conn = get_conn(version_two_path)
        try:
            conn.execute("DROP TABLE runtime_state")
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
        finally:
            conn.close()
        upgraded = clear_runtime_data(version_two_path, backup=False)
        conn = get_conn(version_two_path)
        try:
            check("기존 v2 DB도 데이터 보존 정리", all(
                conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
                for table in ("classification_skills", "classification_logs", "access_logs")
            ))
            check("기존 v2 DB에 채팅 세대 추가", (
                get_chat_session_generation(conn) == upgraded["chat_session_generation"]
                and conn.execute("PRAGMA user_version").fetchone()[0] == 3
            ))
        finally:
            conn.close()

        pre_release_path = Path(directory) / "pre-release-generation-test.db"
        _seed_runtime_data(pre_release_path)
        conn = get_conn(pre_release_path)
        try:
            conn.execute(
                "UPDATE runtime_state SET value = 'unprefixed-pre-release-token' "
                "WHERE key = 'chat_session_generation'"
            )
            conn.commit()
            init_db(conn)
            check("이전 비접두 세대는 초기 기준값으로 정규화", (
                get_chat_session_generation(conn).startswith(
                    CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX
                )
            ))
        finally:
            conn.close()

        concurrent_path = Path(directory) / "concurrent-runtime-test.db"
        _seed_runtime_data(concurrent_path)
        real_backup_database = db_module.backup_database
        writer_started = Event()
        writer_finished = Event()
        writer_errors: list[Exception] = []
        writers: list[Thread] = []
        finished_before_cleanup: list[bool] = []

        def write_during_backup() -> None:
            conn = get_conn(concurrent_path)
            try:
                writer_started.set()
                conn.execute(
                    """INSERT INTO access_logs
                       (persona_id, access_grade, action, doc, section_ids,
                        allowed_count, blocked_count)
                       VALUES ('reviewer', 'C', 'chat', 'keep', '["keep#0"]', 1, 0)"""
                )
                conn.commit()
            except Exception as exc:
                writer_errors.append(exc)
            finally:
                conn.close()
                writer_finished.set()

        def backup_then_start_writer(path, destination=None):
            backup_path = real_backup_database(path, destination)
            writer = Thread(target=write_during_backup, daemon=True)
            writers.append(writer)
            writer.start()
            check("동시 writer 시작", writer_started.wait(1))
            finished_before_cleanup.append(writer_finished.wait(0.25))
            return backup_path

        with patch("app.db.backup_database", side_effect=backup_then_start_writer):
            concurrent = clear_runtime_data(concurrent_path)
        writers[0].join(2)
        check("동시 writer 정상 종료", not writers[0].is_alive() and not writer_errors)
        check("백업부터 삭제까지 새 write 차단", finished_before_cleanup == [False])

        conn = get_conn(concurrent_path)
        backup = get_conn(concurrent["backup_path"])
        try:
            check("백업된 행과 실제 삭제 건수 일치", (
                concurrent["deleted"]["access_logs"] == 1
                and backup.execute("SELECT COUNT(*) FROM access_logs").fetchone()[0] == 1
            ))
            check("정리 완료 뒤 새 로그는 보존", (
                conn.execute("SELECT COUNT(*) FROM access_logs").fetchone()[0] == 1
            ))
        finally:
            backup.close()
            conn.close()

    print("\n런타임 데이터 정리 테스트 통과 ✅")


if __name__ == "__main__":
    main()
