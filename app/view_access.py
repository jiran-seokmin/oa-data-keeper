"""CSO 문서·섹션 접근 결과를 확인하는 콘솔 도구."""

from __future__ import annotations

import argparse

from app import store
from app.engine import decide, document_grade, normalize_grade


def _persona_from_args(args: argparse.Namespace) -> dict:
    if args.persona:
        persona = store.get_persona(args.persona)
        if persona is None:
            raise SystemExit(f"알 수 없는 페르소나: {args.persona}")
        return persona
    return {
        "id": "cli",
        "name": f"CLI {args.grade}",
        "access_grade": normalize_grade(args.grade),
        "department": None,
        "channel": "internal",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="DataKeeper CSO 접근 결과 확인")
    parser.add_argument("--list-docs", action="store_true", help="문서 목록과 Max 등급 표시")
    parser.add_argument("--doc", help="확인할 문서 ID")
    parser.add_argument("--persona", help="DB의 데모 페르소나 ID")
    parser.add_argument("--grade", choices=["O", "S", "C"], default="S", help="직접 지정할 사용자 등급")
    args = parser.parse_args()

    documents = store.load_documents()
    if args.list_docs or not args.doc:
        for document in documents:
            sections = store.sections_for_doc(document["doc"])
            grade = document_grade(sections) or "미정"
            pending = sum(1 for section in sections if section["classification_status"] == "pending_review")
            print(
                f"{document['doc']}: {document['doc_title']} "
                f"[문서등급 {grade}, 섹션 {len(sections)}, 검수대기 {pending}]"
            )
        if not args.doc:
            return

    if not any(document["doc"] == args.doc for document in documents):
        raise SystemExit(f"문서를 찾을 수 없습니다: {args.doc}")

    persona = _persona_from_args(args)
    print(f"\n사용자: {persona['name']} ({persona['access_grade']})")
    for section in store.sections_for_doc(args.doc):
        decision = decide(section, persona)
        print(
            f"\n[{section.get('grade') or '?'}] {section['title']} "
            f"— {'허용' if decision.allowed else '차단'}"
        )
        print(" · ".join(decision.reasons))
        if decision.allowed:
            print(section["text"])


if __name__ == "__main__":
    main()
