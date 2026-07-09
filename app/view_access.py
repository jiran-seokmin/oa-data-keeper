"""CLI 문서 접근 결과 뷰어.

LLM/API 호출 없이 DB(datakeeper.db)와 결정론적 판정 엔진만 사용한다.

예:
  python -m app.view_access --list-docs
  python -m app.view_access --doc ai_sales_strategy_report --clearance 1
  python -m app.view_access --doc ai_sales_strategy_report --persona sales_rep --summary
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

from app.engine import MODE_NAMES, decide
from app.pipeline import load_personas, load_policy, load_sections, mask_text


def doc_map(sections: list[dict]) -> dict[str, str]:
    docs: dict[str, str] = {}
    for section in sections:
        docs.setdefault(section["doc"], section["doc_title"])
    return docs


def find_persona(personas: list[dict], persona_id: str | None, clearance: int | None) -> dict:
    if persona_id is not None:
        for persona in personas:
            if persona["id"] == persona_id:
                return persona
        raise SystemExit(f"알 수 없는 persona id: {persona_id}")

    if clearance is not None:
        matches = [persona for persona in personas if persona["clearance"] == clearance]
        if matches:
            return matches[0]
        raise SystemExit(f"C{clearance} 페르소나가 app/personas.yaml에 없습니다.")

    raise SystemExit("--persona 또는 --clearance 중 하나를 지정하세요.")


def visible_text(section: dict, mode: int) -> tuple[str, str]:
    if mode == 4:
        return "[조회 불가] 접근 차단", ""
    if mode == 3:
        return "[조회 가능: 정보 마스킹본]", mask_text(section["text"], section.get("entities", []))
    if mode == 2:
        return "[조회 가능: 의미 제한 / 일반화 요약]", section.get("summary_generalized", "")
    if mode == 1:
        return (
            "[직접 조회 불가: 노출 제한 / AI 추론 근거 전용]",
            "이 섹션의 원문/요약은 사용자에게 표시되지 않고, 판단·집계 질의의 내부 근거로만 사용됩니다.",
        )
    return "[조회 가능: 전체 접근 / 원문]", section["text"]


def print_doc_list(sections: list[dict]) -> None:
    for i, (doc, title) in enumerate(doc_map(sections).items(), 1):
        print(f"{i:02d}. {doc} | {title}")


def print_summary(doc_sections: list[dict], persona: dict, policy: dict, purpose: str) -> None:
    counts: Counter[int] = Counter()
    print(f"문서: {doc_sections[0]['doc_title']} ({doc_sections[0]['doc']})")
    print(f"사용자: {persona['name']} | C{persona['clearance']} | {persona.get('department') or '외부'} | {persona['channel']}")
    print()
    print("| 섹션 | D | 판정 | 조회 형태 |")
    print("|---|---|---|---|")
    for section in doc_sections:
        decision = decide(section, persona, policy, purpose)
        counts[decision.mode] += 1
        label, _ = visible_text(section, decision.mode)
        print(f"| {section['title']} | D{section['security_level']} | {MODE_NAMES[decision.mode]} | {label} |")
    print()
    print("판정 요약: " + " · ".join(f"A{mode}×{count}" for mode, count in sorted(counts.items())))


def print_detail(doc_sections: list[dict], persona: dict, policy: dict, purpose: str) -> None:
    print(f"문서: {doc_sections[0]['doc_title']} ({doc_sections[0]['doc']})")
    print(f"사용자: {persona['name']} | C{persona['clearance']} | {persona.get('department') or '외부'} | {persona['channel']}")
    print("=" * 100)
    for section in doc_sections:
        decision = decide(section, persona, policy, purpose)
        label, text = visible_text(section, decision.mode)

        print(f"\n[{section['id']}] {section['title']}")
        print(f"등급/판정: D{section['security_level']} -> {MODE_NAMES[decision.mode]}")
        print(f"판정 사유: {' / '.join(decision.reasons)}")
        print("-" * 100)
        print(label)
        if text:
            print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM 없이 문서별 접근 결과를 콘솔에 출력합니다.")
    parser.add_argument("--list-docs", action="store_true", help="사용 가능한 문서 ID 목록을 출력합니다.")
    parser.add_argument("--doc", help="조회할 문서 ID. 예: 01_ai_business_report")
    parser.add_argument("--persona", help="페르소나 ID. 예: external, junior_dev, sales_rep, sales_lead, ceo")
    parser.add_argument("--clearance", type=int, choices=range(5), metavar="0-4", help="사용자 접근 등급 C0~C4")
    parser.add_argument("--purpose", choices=["info", "judgment"], default="info", help="조회 목적. 기본값: info")
    parser.add_argument("--summary", action="store_true", help="섹션별 판정 요약 표만 출력합니다.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    sections = load_sections()

    if args.list_docs:
        print_doc_list(sections)
        return

    if not args.doc:
        raise SystemExit("--doc을 지정하세요. 문서 목록은 --list-docs로 확인할 수 있습니다.")

    docs = doc_map(sections)
    if args.doc not in docs:
        print(f"알 수 없는 문서 ID: {args.doc}", file=sys.stderr)
        print("문서 목록:", file=sys.stderr)
        print_doc_list(sections)
        raise SystemExit(2)

    persona = find_persona(load_personas(), args.persona, args.clearance)
    policy = load_policy()
    doc_sections = [section for section in sections if section["doc"] == args.doc]

    if args.summary:
        print_summary(doc_sections, persona, policy, args.purpose)
    else:
        print_detail(doc_sections, persona, policy, args.purpose)


if __name__ == "__main__":
    main()
