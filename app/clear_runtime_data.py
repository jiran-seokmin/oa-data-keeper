"""Safely clear DataKeeper Skills, chat sessions and audit logs."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.db import DB_PATH, clear_runtime_data, runtime_data_counts


LABELS = {
    "classification_skills": "skills",
    "classification_logs": "classification_logs",
    "access_logs": "access_logs",
    "documents": "documents (preserved)",
    "sections": "sections (preserved)",
    "personas": "personas (preserved)",
}


def _print_counts(counts: dict[str, int]) -> None:
    for table, count in counts.items():
        print(f"  {LABELS[table]}={count}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Classification Skill과 분류·접근 로그를 삭제하고, "
            "모든 브라우저 탭의 채팅 세션을 무효화합니다."
        )
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help="대상 SQLite DB 경로")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="삭제를 실제 적용합니다. 생략하면 대상 건수만 확인합니다.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="백업 없이 삭제합니다(폐기 가능한 테스트 DB 외에는 권장하지 않음).",
    )
    parser.add_argument("--backup-path", type=Path, help="삭제 전 백업 파일 경로")
    args = parser.parse_args()

    if args.no_backup and args.backup_path:
        parser.error("--no-backup과 --backup-path는 함께 사용할 수 없습니다.")
    if not args.apply and (args.no_backup or args.backup_path):
        parser.error("백업 옵션은 --apply와 함께 사용하세요.")

    db_path = args.db.expanduser().resolve()
    try:
        counts = runtime_data_counts(db_path)
    except (FileNotFoundError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"오류: {exc}\n")

    print(f"대상 DB: {db_path}")
    print("현재 건수:")
    _print_counts(counts)
    if not args.apply:
        print("\n미리보기만 수행했습니다. 실제 삭제: 같은 명령에 --apply 추가")
        return

    backup: bool | Path
    if args.no_backup:
        backup = False
    elif args.backup_path:
        backup = args.backup_path
    else:
        backup = True

    try:
        result = clear_runtime_data(db_path, backup=backup)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"삭제 실패: {exc}\n")

    print("\n삭제 완료:")
    _print_counts(result["deleted"])
    print("보존:")
    _print_counts(result["preserved"])
    if result["backup_path"]:
        print(f"백업: {result['backup_path']}")
    else:
        print("백업: 생성하지 않음")
    print(
        "채팅 세션: 전체 무효화 세대 교체 완료 "
        "(열린 탭은 잠시 후, 중지된 탭은 다시 열 때 로컬 transcript 삭제)"
    )
    print("주의: 서버를 계속 사용하면 새로운 Skill과 로그가 다시 생성될 수 있습니다.")


if __name__ == "__main__":
    main()
