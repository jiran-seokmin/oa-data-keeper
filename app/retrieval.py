"""CSO 권한 우선 섹션 검색.

검색은 항상 접근 판정을 먼저 적용한다. 사용자의 O/S/C 권한보다 높은 섹션과
검수 대기 섹션은 키워드 매칭·검색 결과·LLM 컨텍스트 어느 곳에도 진입하지 않는다.
허용되지 않은 섹션에는 어떤 형태로도 검색 결과를 생성하지 않는다.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence

from app import store
from app.engine import decide


FILLER = {
    "있나요", "있는지", "있어요", "있을", "없나요", "어디", "어디가", "무엇", "뭐야", "뭔가요",
    "인가요", "일까요", "까요", "알려", "알려줘", "주세요", "관련", "관련해서", "현재", "요즘",
    "우리", "저희", "대해", "대해서", "좀", "그리고", "중인", "건이", "건은", "것은", "무슨",
    "어떤", "어떻게", "얼마", "얼마인가요", "정도",
}
MAX_CONTEXT_QUESTIONS = 5


def _tokens(question: str) -> list[str]:
    raw = re.split(r"[\s,\.\?!·:;/\(\)\[\]\"'’]+", question)
    return [token.lower() for token in raw if len(token) >= 2 and token not in FILLER]


def normalize_context_questions(context_questions: Sequence[str] | None) -> list[str]:
    """Return a small, whitespace-normalized list of prior questions."""

    if not context_questions:
        return []
    normalized = [
        " ".join(question.split())
        for question in context_questions
        if isinstance(question, str) and question.strip()
    ]
    return normalized[-MAX_CONTEXT_QUESTIONS:]


def search(
    question: str,
    persona: dict,
    conn: sqlite3.Connection | None = None,
    *,
    context_questions: Sequence[str] | None = None,
) -> list[dict]:
    """DB의 확정 섹션 중 현재 사용자가 접근 가능한 검색 결과만 반환한다."""
    own = conn is None
    conn = conn or store.get_conn()
    try:
        # SQL 단계에서 권한 밖/미확정 원문을 먼저 제거한다.
        return search_sections_with_context(
            question,
            context_questions,
            persona,
            store.load_accessible_sections(persona, conn),
        )
    finally:
        if own:
            conn.close()


def search_sections(question: str, persona: dict, sections: list[dict]) -> list[dict]:
    tokens = _tokens(question)
    if not tokens:
        return []

    results: list[dict] = []
    for section in sections:
        decision = decide(section, persona)
        if not decision.allowed:
            continue

        keywords = section.get("keywords", [])
        summary = section.get("summary", "")
        match_text = " ".join(
            [section.get("title", ""), section.get("text", ""), summary, *keywords]
        ).lower()
        matched = sorted({token for token in tokens if token in match_text})
        if not matched:
            continue

        results.append({
            "id": section["id"],
            "doc": section["doc"],
            "doc_title": section["doc_title"],
            "title": section["title"],
            "grade": section["grade"],
            "content": section["text"],
            "summary": summary,
            "matched": matched,
            "access": "allowed",
            "reasons": decision.reasons,
        })

    results.sort(key=lambda result: (-len(result["matched"]), result["id"]))
    return results


def search_sections_with_context(
    question: str,
    context_questions: Sequence[str] | None,
    persona: dict,
    sections: list[dict],
) -> list[dict]:
    """Search the current question first, then use prior questions for a follow-up miss."""

    results = search_sections(question, persona, sections)
    if results:
        return results
    context = normalize_context_questions(context_questions)
    if not context:
        return []
    return search_sections("\n".join([*context, question]), persona, sections)


def access_counts(persona: dict, sections: list[dict]) -> tuple[int, int]:
    """(허용 섹션 수, 차단/미확정 섹션 수)를 반환한다."""
    allowed = sum(1 for section in sections if decide(section, persona).allowed)
    return allowed, len(sections) - allowed
