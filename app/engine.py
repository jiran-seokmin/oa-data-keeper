"""접근 제어 판정 엔진.

A(접근 모드) = Engine(D 데이터 보안 등급, C 사용자 접근 등급, Context)

판정은 반드시 결정론적 코드로만 수행한다. LLM은 이해(분류·요약·추출)에만 쓰이고,
접근 판정 자체에는 관여하지 않는다 — 감사 가능성과 인젝션 내성을 위한 핵심 설계 원칙.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

MODE_NAMES = {
    0: "A0 차단",
    1: "A1 마스킹",
    2: "A2 의미 제한",
    3: "A3 노출 제한",
    4: "A4 전체 접근",
}

LEVEL_NAMES = {
    0: "D0 외부 정보",
    1: "D1 일반 정보",
    2: "D2 제한 접근",
    3: "D3 기밀 접근",
    4: "D4 최고 접근",
}


@dataclass
class Decision:
    mode: int
    base_mode: int
    security_level: int
    clearance: int
    gap: int
    reasons: list[str] = field(default_factory=list)

    @property
    def mode_name(self) -> str:
        return MODE_NAMES[self.mode]


def load_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def base_mode_for_gap(gap: int) -> int:
    if gap >= 0:
        return 4
    if gap == -1:
        return 2
    if gap == -2:
        return 1
    return 0


def decide(section: dict, persona: dict, policy: dict, purpose: str = "info") -> Decision:
    """섹션 하나에 대한 접근 모드 판정.

    purpose: "info"(정보 조회) | "judgment"(판단/집계 질의 — A3 승격 후보)
    """
    # default-deny: 등급이 없으면 최고 등급으로 간주
    d = section.get("security_level")
    if d is None:
        d = 4
    c = persona["clearance"]
    gap = c - d
    reasons: list[str] = []

    # 외부 채널 하드 캡: D0만 공개, 나머지 전면 차단
    if persona.get("channel") == "external" and policy["external_channel"]["public_only"]:
        if d == 0:
            return Decision(4, 4, d, c, gap, ["외부 채널: D0 공개 정보만 전체 접근"])
        return Decision(0, 0, d, c, gap, ["외부 채널: D0 외 전면 차단 (하드 캡)"])

    if d == 0:
        return Decision(4, 4, d, c, gap, ["D0 공개 정보"])

    base = base_mode_for_gap(gap)
    mode = base
    reasons.append(f"기본 매트릭스: gap={gap} → {MODE_NAMES[base]}")

    modifiers = policy.get("modifiers", {})

    # 부서 관련성 보정: 담당 부서 데이터면 +1단계 (D4 제외, A0에서는 부활 불가)
    if (
        modifiers.get("department_boost", {}).get("enabled")
        and d < 4
        and base >= 1
        and persona.get("department")
        and persona["department"] in section.get("departments", [])
    ):
        if mode < 4:
            mode = min(mode + 1, 4)
            reasons.append(f"부서 관련성(+1): {persona['department']} 담당 데이터 → {MODE_NAMES[mode]}")

    # 판단/집계 질의: A1/A2 판정 섹션을 A3(노출 제한)로 승격 (D4 제외)
    if (
        purpose == "judgment"
        and modifiers.get("judgment_a3", {}).get("enabled")
        and d < 4
        and base >= 1
        and mode < 3
    ):
        mode = 3
        reasons.append("판단/집계 질의: 추론 근거 전용(A3)으로 승격 — 내용 직접 언급 금지")

    if d == 4 and mode != base:
        # 방어적 불변식 — 위 조건들이 d<4를 요구하므로 도달하지 않아야 한다
        mode = base
        reasons.append("D4 불변 규칙: 컨텍스트 보정 무효화")

    return Decision(mode, base, d, c, gap, reasons)


def decide_all(sections: list[dict], persona: dict, policy: dict, purpose: str = "info") -> list[tuple[dict, Decision]]:
    return [(s, decide(s, persona, policy, purpose)) for s in sections]
