"""Legacy D0-D4/C0-C4 SQLite database -> CSO migration CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.db import DB_PATH, migrate_legacy_db


def main() -> None:
    parser = argparse.ArgumentParser(description="DataKeeper DB를 C/S/O 스키마로 안전하게 마이그레이션")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="대상 SQLite DB 경로")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="백업을 만들지 않음(임시 테스트 DB 외에는 권장하지 않음)",
    )
    parser.add_argument("--backup-path", type=Path, help="백업 파일 경로")
    args = parser.parse_args()

    if args.no_backup and args.backup_path:
        parser.error("--no-backup과 --backup-path는 함께 사용할 수 없습니다.")

    backup: bool | Path
    if args.no_backup:
        backup = False
    elif args.backup_path:
        backup = args.backup_path
    else:
        backup = True

    result = migrate_legacy_db(args.db, backup=backup)
    if result["migrated"]:
        print("CSO 마이그레이션 완료")
    elif result["initialized"]:
        print("빈 CSO 데이터베이스 초기화 완료")
    else:
        print("이미 최신 CSO 스키마입니다")
    print(
        f"  documents={result['documents']} sections={result['sections']} "
        f"personas={result['personas']}"
    )
    if result.get("backup_path"):
        print(f"  backup={result['backup_path']}")


if __name__ == "__main__":
    main()
