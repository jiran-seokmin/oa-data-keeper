"""접근제어 검색 유출·판정 테스트. 실행: python tests/test_retrieval.py (API 불필요)

자체 완결: 임시 DB에 samples를 시딩한 뒤 store/retrieval을 검증한다.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import retrieval, store
from app.engine import load_yaml
from app.seed_db import seed

POLICY = load_yaml("app/policy.yaml")

EXTERNAL = {"name": "외부 고객", "clearance": 0, "department": None, "channel": "external"}
JUNIOR = {"name": "신입 개발자", "clearance": 1, "department": "개발팀", "channel": "internal"}
SALES_REP = {"name": "영업팀원", "clearance": 2, "department": "영업팀", "channel": "internal"}
SALES_LEAD = {"name": "영업팀장", "clearance": 3, "department": "영업팀", "channel": "internal"}
CEO = {"name": "CEO", "clearance": 4, "department": "경영진", "channel": "internal"}
ALL = [EXTERNAL, JUNIOR, SALES_REP, SALES_LEAD, CEO]

MNA = "ai_sales_strategy_report#4"  # 비공개 인수 검토 (D4)

_fails = 0


def check(name, cond):
    global _fails
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    if not cond:
        _fails += 1


def find(results, sid):
    return next((r for r in results if r["id"] == sid), None)


def run(conn):
    def q(text, persona, purpose="info"):
        return retrieval.search(text, persona, POLICY, purpose, conn)

    # ── 시딩 결과 ──
    secs = store.load_sections(conn)
    check("시딩: 섹션 21개", len(secs) == 21)

    # ── 유출 방지 ──
    check("C0 외부 'M&A 원문 엔티티' 검색 → 0건 (존재 은닉)",
          len(q("실드락 인수 프로젝트 오로라", EXTERNAL)) == 0)
    check("C2 마스킹된 원문 엔티티('실드락')로 검색 → 0건",
          len(q("실드락", SALES_REP)) == 0)

    # ── D4 인수검토: 등급별 렌더 ──
    c1 = q("인수 검토", JUNIOR)
    check("C1 신입: D4 인수검토는 결과에 없음 (A4 존재 은닉)", find(c1, MNA) is None)

    c2 = find(q("인수 검토", SALES_REP), MNA)
    check("C2 영업원: 인수검토 A3 마스킹으로 노출", c2 and c2["mode"] == 3)
    check("C2 마스킹본에 원문 '실드락' 없음", c2 and "실드락" not in c2["rendered"])
    check("C2 마스킹본에 플레이스홀더 '[기업명A]' 포함", c2 and "[기업명A]" in c2["rendered"])

    c3 = find(q("인수 검토", SALES_LEAD), MNA)
    check("C3 팀장: 인수검토 A1 노출제한", c3 and c3["mode"] == 1)
    check("C3 A1은 본문 미공개(content_hidden)", c3 and c3["content_hidden"] is True)
    check("C3 A1 rendered에 원문 '실드락' 없음", c3 and "실드락" not in c3["rendered"])

    c4 = find(q("인수 검토", CEO), MNA)
    check("C4 CEO: 인수검토 A0 원문", c4 and c4["mode"] == 0)
    check("C4 원문에 '실드락' 포함", c4 and "실드락" in c4["rendered"])

    # ── 불변식: 어떤 페르소나·질의에도 A4 섹션은 결과에 없음 ──
    broad = "고객 계약 인수 보상 평가 점검 매출 가격 재무 검토 현황"
    no_a4 = all(r["mode"] != 4 for p in ALL for r in q(broad, p))
    check("불변식: A4 섹션은 결과에 절대 미포함", no_a4)

    # ── 불변식: A3 마스킹 결과엔 해당 섹션 원문 엔티티가 남지 않음 ──
    leak = False
    for p in ALL:
        for r in q(broad, p):
            if r["mode"] == 3:
                s = next(x for x in secs if x["id"] == r["id"])
                if any(e["text"] in r["rendered"] for e in s["entities"]):
                    leak = True
    check("불변식: A3 마스킹본에 원문 엔티티 잔존 없음", not leak)

    # ── 대표 시나리오: '논의 중인 고객사' 등급별 결과 ──
    # C0 외부는 D0 공개 섹션만 볼 수 있다 (개요에 '고객사명'이 있어 히트할 수 있으나 전부 D0).
    ext_res = q("논의 중인 고객사", EXTERNAL)
    check("C0 외부 결과는 전부 D0 공개", all(r["security_level"] == 0 for r in ext_res))
    check("C0 외부: 기밀 파이프라인(D2)은 미노출",
          find(ext_res, "ai_sales_strategy_report#1") is None)
    rep = find(q("논의 중인 고객사", SALES_REP), "ai_sales_strategy_report#1")
    check("C2 영업원 파이프라인 A0 원문 노출", rep and rep["mode"] == 0)
    jun = find(q("논의 중인 고객사", JUNIOR), "ai_sales_strategy_report#1")
    check("C1 신입 파이프라인 A2 요약으로 대체", jun and jun["mode"] == 2)


def main():
    tmp = tempfile.mktemp(suffix=".db")
    seed(tmp)
    conn = store.get_conn(tmp)
    try:
        run(conn)
    finally:
        conn.close()
        os.remove(tmp)
    print(f"\n{'모든 테스트 통과 ✅' if _fails == 0 else f'{_fails}개 실패 ❌'}")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
