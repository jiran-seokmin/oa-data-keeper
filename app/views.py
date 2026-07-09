"""판정 결과를 프론트(그리드·뷰어·매트릭스)용 뷰 모델로 변환.

판정은 engine.decide()가 담당하고, 여기서는 등급(A모드)에 맞는 표시용 콘텐츠만 조립한다.
A모드 표기는 PRD/CONCEPT canonical (A0 전체 접근 … A4 접근 차단)을 따른다.

유출 방지: 제한 모드의 원문은 그대로 내보내지 않는다.
  A0 전체 접근  → 원문 세그먼트(엔티티 하이라이트)
  A1 노출 제한  → 마스킹본을 블러용으로만 (원문 값 미노출)
  A2 의미 제한  → 일반화 요약만
  A3 정보 마스킹 → 마스킹본 세그먼트(플레이스홀더)
  A4 접근 차단  → 콘텐츠 없음 (시각화에서는 잠금 표시)
"""

from __future__ import annotations

from app.engine import Decision, LEVEL_NAMES, MODE_NAMES

# A모드별 표시 종류
KIND = {0: "full", 1: "exposure", 2: "semantic", 3: "mask", 4: "blocked"}


def _segments(text: str, entities: list[dict], mask: bool) -> list[dict]:
    """엔티티 기준으로 텍스트를 세그먼트로 분할.

    mask=False → 엔티티를 'hl'(하이라이트)로, mask=True → 'mask'(플레이스홀더)로.
    """
    out: list[dict] = []
    rest = text
    ents = entities or []
    while rest:
        best = -1
        chosen = None
        for e in ents:
            i = rest.find(e["text"])
            if i >= 0 and (best < 0 or i < best):
                best, chosen = i, e
        if best < 0:
            out.append({"text": rest, "kind": "plain"})
            break
        if best > 0:
            out.append({"text": rest[:best], "kind": "plain"})
        if mask:
            out.append({"text": chosen["placeholder"], "kind": "mask"})
        else:
            out.append({"text": chosen["text"], "kind": "hl"})
        rest = rest[best + len(chosen["text"]):]
    return out


def _mask_text(text: str, entities: list[dict]) -> str:
    for e in sorted(entities or [], key=lambda e: len(e["text"]), reverse=True):
        text = text.replace(e["text"], e["placeholder"])
    return text


def _d_name(level: int | None) -> str:
    if level is None:
        return "미분류"
    return LEVEL_NAMES[level].split(" ", 1)[1]


def section_view(section: dict, decision: Decision) -> dict:
    """섹션 하나에 대한 뷰 모델 (판정 근거 + 등급별 표시 콘텐츠)."""
    mode = decision.mode
    view = {
        "id": section["id"],
        "doc": section["doc"],
        "doc_title": section["doc_title"],
        "title": section["title"],
        "d": section["security_level"],
        "d_name": _d_name(section["security_level"]),
        "mode": mode,
        "mode_name": MODE_NAMES[mode],
        "gap": decision.gap,
        "reason": " · ".join(decision.reasons),
        "reasons": decision.reasons,
        "keywords": section.get("keywords", []),
        "summary": section.get("summary_generalized", ""),
        "departments": section.get("departments", []),
        "kind": KIND[mode],
    }
    entities = section.get("entities", [])
    if mode == 0:
        view["segments"] = _segments(section["text"], entities, mask=False)
    elif mode == 1:
        view["blur_text"] = _mask_text(section["text"], entities)
    elif mode == 3:
        view["segments"] = _segments(section["text"], entities, mask=True)
    return view
