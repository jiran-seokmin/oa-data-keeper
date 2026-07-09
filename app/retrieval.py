"""접근제어 키워드 검색 (1단계 · 결정론적, 런타임 LLM 없음).

유출 방지가 제1 원칙이다. 반드시 이 순서를 지킨다 (PRD §7):
  1) 후보 로드 (외부 채널은 D0만 코스 필터)
  2) engine.decide()로 접근 필터 — A4 섹션은 여기서 완전히 제거 (인덱스 진입 차단, 존재 은닉)
  3) 등급별 렌더 (A0 원문 / A1 열람불가 / A2 요약 / A3 마스킹)
  4) 렌더된 표현 위에서만 키워드 매칭 — 숨겨진 엔티티(원문 값)로는 절대 히트하지 않음

각 결과는 판정 근거(D등급·A모드·gap·reasons)를 함께 담아 투명성을 확보한다.
"""

from __future__ import annotations

import re
import sqlite3

from app.engine import MODE_NAMES, decide, load_yaml
from app.pipeline import mask_text
from app import store

POLICY_PATH = "app/policy.yaml"

# A1 노출 제한: 본문은 검색 대상에서 제외하고(직접 열람 불가), 존재만 메타데이터로 고지.
A1_NOTICE = "관련 제한 정보가 존재하나 직접 열람할 수 없습니다 (AI 추론 근거 전용)."


# 내용가치 없는 질문 filler — 매칭 노이즈 제거용 (2자 이상만 등재; 1자는 len 필터로 제거됨)
FILLER = {
    "있나요", "있는지", "있어요", "있을", "없나요", "어디", "어디가", "무엇", "뭐야", "뭔가요",
    "인가요", "일까요", "까요", "알려", "알려줘", "주세요", "관련", "관련해서", "현재", "요즘",
    "우리", "저희", "대해", "대해서", "좀", "그리고", "중인", "건이", "건은", "것은", "무슨",
    "어떤", "어떻게", "얼마", "얼마인가요", "정도",
}


def _tokens(question: str) -> list[str]:
    """질문을 검색 토큰으로 분해 (2자 이상, filler 제외)."""
    raw = re.split(r"[\s,\.\?!·:;/\(\)\[\]\"'’]+", question)
    return [t.lower() for t in raw if len(t) >= 2 and t not in FILLER]


def _render(section: dict, mode: int) -> tuple[str, str]:
    """(표시용 rendered, 매칭 대상 match_text) 반환.

    match_text에는 숨겨진 원문 값이 절대 들어가지 않는다.
    """
    meta = f"{section['title']} {' '.join(section.get('keywords', []))}"
    if mode == 0:  # A0 전체 접근: 원문
        return section["text"], f"{section['text']} {meta}"
    if mode == 1:  # A1 노출 제한: 본문 미공개 → 제목·키워드로만 매칭 (존재 고지)
        return A1_NOTICE, meta
    if mode == 2:  # A2 의미 제한: 일반화 요약만
        summary = section.get("summary_generalized", "")
        return summary, f"{summary} {meta}"
    if mode == 3:  # A3 정보 마스킹: 마스킹본 (엔티티는 플레이스홀더로 치환됨)
        masked = mask_text(section["text"], section.get("entities", []))
        return masked, f"{masked} {meta}"
    # mode 4 (A4)는 호출 전에 제거된다
    raise ValueError(f"A4 섹션은 렌더 대상이 아니다: {section['id']}")


def search(
    question: str,
    persona: dict,
    policy: dict | None = None,
    purpose: str = "info",
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    if policy is None:
        policy = load_yaml(POLICY_PATH)

    own = conn is None
    conn = conn or store.get_conn()
    try:
        external = persona.get("channel") == "external"
        sections = store.load_sections(conn, external_only=external)

        tokens = _tokens(question)
        results: list[dict] = []
        for s in sections:
            d = decide(s, persona, policy, purpose)
            if d.mode == 4:
                continue  # A4: 인덱스 진입 자체 차단 (존재 은닉)

            rendered, match_text = _render(s, d.mode)
            haystack = match_text.lower()
            matched = [t for t in tokens if t in haystack]
            if not matched:
                continue

            results.append({
                "id": s["id"],
                "doc": s["doc"],
                "doc_title": s["doc_title"],
                "title": s["title"],
                "security_level": s["security_level"],
                "mode": d.mode,
                "mode_name": MODE_NAMES[d.mode],
                "gap": d.gap,
                "reasons": d.reasons,
                "rendered": rendered,
                "content_hidden": d.mode == 1,  # A1은 본문 미공개
                "matched": sorted(set(matched)),
            })

        # 관련도(매칭 토큰 수) 내림차순, 동률은 문서·섹션 순
        results.sort(key=lambda r: (-len(r["matched"]), r["id"]))
        return results
    finally:
        if own:
            conn.close()
