"""판정 엔진 시나리오 테스트. 실행: python tests/test_engine.py (API 불필요)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import decide
from app.pipeline import forbidden_strings, load_policy, mask_text, scan_leaks

POLICY = load_policy()

EXTERNAL = {"name": "외부 고객", "clearance": 0, "department": None, "channel": "external"}
JUNIOR = {"name": "신입 개발자", "clearance": 1, "department": "개발팀", "channel": "internal"}
SALES_REP = {"name": "영업팀원", "clearance": 2, "department": "영업팀", "channel": "internal"}
SALES_LEAD = {"name": "영업팀장", "clearance": 3, "department": "영업팀", "channel": "internal"}
CEO = {"name": "CEO", "clearance": 4, "department": "경영진", "channel": "internal"}


def sec(level, departments=None):
    return {"security_level": level, "departments": departments or [], "entities": []}


def check(name, actual, expected):
    status = "OK " if actual == expected else "FAIL"
    print(f"[{status}] {name}: mode={actual} (expected {expected})")
    assert actual == expected, name


# 외부 채널 하드 캡
check("외부 × D0 → A0", decide(sec(0), EXTERNAL, POLICY).mode, 0)
check("외부 × D1 → A4", decide(sec(1), EXTERNAL, POLICY).mode, 4)
check("외부 × D2 (판단 질의여도) → A4", decide(sec(2), EXTERNAL, POLICY, "judgment").mode, 4)

# D0는 누구에게나 공개
check("신입 × D0 → A0", decide(sec(0), JUNIOR, POLICY).mode, 0)

# 기본 매트릭스 (gap = C - D)
check("신입 C1 × D1 (gap 0) → A0", decide(sec(1), JUNIOR, POLICY).mode, 0)
check("신입 C1 × D2 (gap -1) → A2", decide(sec(2), JUNIOR, POLICY).mode, 2)
check("신입 C1 × D3 (gap -2) → A3", decide(sec(3), JUNIOR, POLICY).mode, 3)

# D4 특칙: 최신 슬라이드 13의 최고 접근 정보 행(A4/A4/A3/A1/A0)
check("외부 C0 × D4 → A4", decide(sec(4), EXTERNAL, POLICY).mode, 4)
check("신입 C1 × D4 → A4", decide(sec(4), JUNIOR, POLICY).mode, 4)
check("영업팀원 C2 × D4 → A3", decide(sec(4), SALES_REP, POLICY).mode, 3)
check("영업팀장 C3 × D4 → A1", decide(sec(4), SALES_LEAD, POLICY).mode, 1)
check("CEO C4 × D4 → A0", decide(sec(4), CEO, POLICY).mode, 0)

# 부서 관련성 보정 (+1단계 완화)
check("영업팀원 C2 × D3 영업 데이터 (gap -1, 부서 일치) → A1",
      decide(sec(3, ["영업팀"]), SALES_REP, POLICY).mode, 1)
check("영업팀원 C2 × D3 타부서 데이터 (gap -1) → A2",
      decide(sec(3, ["재무팀"]), SALES_REP, POLICY).mode, 2)
check("영업팀장 C3 × D3 영업 데이터 (gap 0) → A0",
      decide(sec(3, ["영업팀"]), SALES_LEAD, POLICY).mode, 0)

# D4 불변 규칙: 부서가 일치해도 최신 슬라이드 D4 행에서 상승 없음
check("영업팀장 C3 × D4 영업 데이터 → A1 (부서 보정 없음)",
      decide(sec(4, ["영업팀"]), SALES_LEAD, POLICY).mode, 1)

# 판단/집계 질의 → A1 완화
check("신입 C1 × D3 판단 질의 (gap -2) → A1", decide(sec(3), JUNIOR, POLICY, "judgment").mode, 1)
check("신입 C1 × D2 판단 질의 (gap -1) → A1", decide(sec(2), JUNIOR, POLICY, "judgment").mode, 1)
check("신입 C1 × D4 판단 질의 (gap -3) → A4 (완화 불가)", decide(sec(4), JUNIOR, POLICY, "judgment").mode, 4)
check("CEO C4 × D3 판단 질의 → A0 (하향 없음)", decide(sec(3), CEO, POLICY, "judgment").mode, 0)

# default-deny: 등급 없는 섹션은 관리자 검수 전 접근 차단
check("신입 × 미분류 섹션 → A4", decide({"departments": []}, JUNIOR, POLICY).mode, 4)
check("CEO × 미분류 섹션 → A4", decide({"departments": []}, CEO, POLICY).mode, 4)

# 마스킹: 긴 엔티티 우선 치환
masked = mask_text(
    "한빛제조는 연 4억 원, 미래금융은 연 6억 원 규모.",
    [
        {"text": "한빛제조", "placeholder": "[고객사A]"},
        {"text": "미래금융", "placeholder": "[고객사B]"},
        {"text": "연 4억 원", "placeholder": "[금액A]"},
        {"text": "연 6억 원", "placeholder": "[금액B]"},
    ],
)
assert masked == "[고객사A]는 [금액A], [고객사B]은 [금액B] 규모.", masked
print("[OK ] 엔티티 마스킹")

# 출력 가드: 제한 섹션 엔티티 − A0 허용 엔티티
from app.engine import Decision

s_restricted = {"security_level": 3, "entities": [{"text": "미래금융", "type": "고객사"}, {"text": "94%", "type": "수치"}]}
s_allowed = {"security_level": 2, "entities": [{"text": "미래금융", "type": "고객사"}]}
decisions = [
    (s_restricted, Decision(1, 3, 3, 1, -2)),
    (s_allowed, Decision(0, 0, 2, 1, -1)),
]
fb = forbidden_strings(decisions)
assert fb == ["94%"], fb  # 미래금융은 A0 섹션에서 허용되므로 제외
assert scan_leaks("달성률은 94% 수준입니다", fb) == ["94%"]
assert scan_leaks("목표에 근접할 전망입니다", fb) == []
print("[OK ] 출력 가드 유출 스캔")

print("\n전체 테스트 통과 ✅")
