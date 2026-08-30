"""Explicit C/S/O sample database initialization command.

This is the only CLI entry point that writes `data/samples/*.md` into
`datakeeper.db`. Importing or running the API server must not classify or seed
sample documents implicitly.
"""

from __future__ import annotations

import argparse
import sys

from app.db import DB_PATH
from app.seed_db import report, seed


def main() -> None:
    parser = argparse.ArgumentParser(description="samples 문서를 C/S/O 등급으로 명시적으로 초기화")
    parser.add_argument("--reset", action="store_true", help="스키마 재생성 후 C/S/O samples를 DB에 저장")
    parser.add_argument("--report", action="store_true", help="DB 생성 없이 C/S/O 시드 미매칭 점검")
    parser.add_argument("--strict", action="store_true", help="GRADES 미지정 섹션이 있으면 실패 코드 반환")
    args = parser.parse_args()

    if args.report:
        raise SystemExit(report())

    if not args.reset:
        parser.print_help()
        print("\nDB 쓰기 작업은 수행하지 않았습니다. 초기화하려면 --reset을 붙이세요.")
        raise SystemExit(0)

    stats = seed()
    print(f"샘플 초기화 완료: {DB_PATH}")
    print(
        f"  documents={stats['documents']} sections={stats['sections']} "
        f"personas={stats['personas']} events={stats['classification_events']} "
        f"pending_review={stats['pending_review']}"
    )
    grades = ", ".join(
        f"{doc}={grade or 'pending_review'}"
        for doc, grade in sorted(stats["document_grades"].items())
    )
    print(f"  document_grade(Max): {grades}")
    if stats["missing"]:
        print(f"GRADES 미지정(grade=None, pending_review): {stats['missing']}", file=sys.stderr)
        if args.strict:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
