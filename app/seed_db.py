"""samples 직접 DB 시딩 내부 모듈 — data/samples/*.md → SQLite (datakeeper.db)

중간 산출물 없이 samples를 DB로 변환하는 함수들을 제공한다.

  python -m app.init_samples --reset  # 명시적 샘플 초기화: samples → SQLite
  python -m app.seed_db --report      # 등급 시드 병합 결과·미매칭 점검 (DB 미생성)

등급 시드(GRADES)는 Claude 개발단계 분석을 사람이 발표 슬라이드 등급표와 대조·검토해 커밋한
정적 데이터다(런타임 LLM 없음). 섹션 id는 반드시 split_semantic_sections() 출력에 맞춘다 —
불일치하면 해당 섹션은 조용히 D4로 격리된다(default-deny).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.db import DB_PATH, get_conn, init_db

# 플레이스홀더 로직은 공용 모듈 것을 재사용한다 (중복 구현 금지).
from app.ingest import assign_placeholders

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"

DEFAULT_CONFIDENCE = 0.95

# ── 페르소나 (personas 테이블 시드) ───────────────────────────────────────
PERSONAS = [
    {"id": "external", "name": "외부 고객", "clearance": 0, "department": None, "channel": "external"},
    {"id": "junior_dev", "name": "신입 개발자", "clearance": 1, "department": "개발팀", "channel": "internal"},
    {"id": "sales_rep", "name": "영업팀원", "clearance": 2, "department": "영업팀", "channel": "internal"},
    {"id": "sales_lead", "name": "영업팀장", "clearance": 3, "department": "영업팀", "channel": "internal"},
    {"id": "ceo", "name": "CEO", "clearance": 4, "department": "경영진", "channel": "internal"},
]

# ── 등급 시드 (원본 heading 섹션 id → 분류 결과) ─────────────────────────
# id = "<파일stem>#<heading인덱스>". DB 저장은 문단/의미 단위 id("<파일stem>#<chunk인덱스>")
# 로 확장하지만, 등급 시드는 사람이 검수한 heading 단위 기준을 문단 chunk에 상속한다.
# entities는 text/type만 — placeholder는 assign_placeholders가 코퍼스 전역으로 부여한다.
GRADES: dict[str, dict] = {
    # ── AI 사업 전략 보고서 (D0/D2/D3/D4 혼재 — 대표 데모 문서) ──
    "ai_sales_strategy_report#0": {
        "security_level": 0,
        "keywords": ["공개 자료", "제품 개요"],
        "departments": [],
        "summary_generalized": "접근 제어 엔진 제품의 공개 소개와 데모 운영 방향.",
        "entities": [],
    },
    "ai_sales_strategy_report#1": {
        "security_level": 2,
        "keywords": ["영업 파이프라인", "고객 현황", "논의 중 고객사"],
        "departments": ["영업팀"],
        "summary_generalized": "다수의 기업 고객과 제품 도입을 논의 중이며 일부는 기술 검증 단계에 있음.",
        "entities": [
            {"text": "한빛전자", "type": "고객사"},
            {"text": "대한모빌리티", "type": "고객사"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "라온제약", "type": "고객사"},
            {"text": "코어물류", "type": "고객사"},
            {"text": "다온커머스", "type": "고객사"},
            {"text": "미래카드", "type": "고객사"},
            {"text": "18개사", "type": "수치"},
        ],
    },
    "ai_sales_strategy_report#2": {
        "security_level": 3,
        "keywords": ["계약 규모", "예상 매출", "기대 매출"],
        "departments": ["영업팀", "재무팀"],
        "summary_generalized": "파이프라인 기준 예상 계약 규모와 기대 매출을 수십억 원대 규모로 관리 중.",
        "entities": [
            {"text": "52억", "type": "금액"},
            {"text": "31억", "type": "금액"},
            {"text": "12억", "type": "금액"},
            {"text": "10억", "type": "금액"},
            {"text": "8억", "type": "금액"},
            {"text": "5억", "type": "금액"},
            {"text": "4억", "type": "금액"},
            {"text": "한빛전자", "type": "고객사"},
            {"text": "대한모빌리티", "type": "고객사"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "라온제약", "type": "고객사"},
            {"text": "코어물류", "type": "고객사"},
        ],
    },
    "ai_sales_strategy_report#3": {
        "security_level": 3,
        "keywords": ["가격 전략", "경쟁 입찰", "할인"],
        "departments": ["영업팀"],
        "summary_generalized": "일부 대형 건에서 경쟁사와 가격 경쟁이 있으며 단계별 도입 패키지로 대응.",
        "entities": [
            {"text": "넥스가드", "type": "경쟁사"},
            {"text": "9퍼센트", "type": "수치"},
            {"text": "한빛전자", "type": "고객사"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "7월 26일", "type": "일정"},
        ],
    },
    "ai_sales_strategy_report#4": {
        "security_level": 4,
        "keywords": ["M&A", "인수 검토", "비공개"],
        "departments": ["경영진"],
        "summary_generalized": "비공개 전략 검토 사안이 존재함(내용 비공개).",
        "entities": [
            {"text": "실드락", "type": "기업명"},
            {"text": "프로젝트 오로라", "type": "코드명"},
            {"text": "85억", "type": "금액"},
            {"text": "110억", "type": "금액"},
            {"text": "6개월", "type": "수치"},
            {"text": "대표이사", "type": "직위"},
            {"text": "CFO", "type": "직위"},
            {"text": "전략기획실장", "type": "직위"},
        ],
    },
    "ai_sales_strategy_report#5": {
        "security_level": 4,
        "keywords": ["재무 전망", "투자 유치", "런웨이"],
        "departments": ["재무팀", "경영진"],
        "summary_generalized": "손익분기·투자 유치 관련 비공개 재무 전망이 존재함(수치 비공개).",
        "entities": [
            {"text": "160억", "type": "금액"},
            {"text": "15개월", "type": "수치"},
            {"text": "2027년 2분기", "type": "일정"},
            {"text": "시리즈 B", "type": "수치"},
        ],
    },
    # ── 엔터프라이즈 계약 협상 메모 ──
    "enterprise_contract_negotiation#0": {
        "security_level": 2,
        "keywords": ["계약 개요", "우선 협상 고객"],
        "departments": ["영업팀"],
        "summary_generalized": "복수의 우선 협상 고객이 있으며 도입 목적과 보안 요구가 상이함.",
        "entities": [
            {"text": "한빛전자", "type": "고객사"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "대한모빌리티", "type": "고객사"},
        ],
    },
    "enterprise_contract_negotiation#1": {
        "security_level": 2,
        "keywords": ["고객 요구사항", "보안 요구"],
        "departments": ["영업팀"],
        "summary_generalized": "고객별로 협력사 공유·권한 분리·망분리 등 서로 다른 보안 요구를 제시.",
        "entities": [
            {"text": "한빛전자", "type": "고객사"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "대한모빌리티", "type": "고객사"},
        ],
    },
    "enterprise_contract_negotiation#2": {
        "security_level": 3,
        "keywords": ["제안 금액", "할인 조건", "보상 한도"],
        "departments": ["영업팀", "재무팀"],
        "summary_generalized": "대형 건별 제안 금액과 할인·보상 조건을 협상 중(구체 수치 비공개).",
        "entities": [
            {"text": "12억", "type": "금액"},
            {"text": "10억", "type": "금액"},
            {"text": "8억", "type": "금액"},
            {"text": "1.5억", "type": "금액"},
            {"text": "20퍼센트", "type": "수치"},
            {"text": "200퍼센트", "type": "수치"},
            {"text": "한빛전자", "type": "고객사"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "대한모빌리티", "type": "고객사"},
        ],
    },
    "enterprise_contract_negotiation#3": {
        "security_level": 2,
        "keywords": ["법무 검토", "계약 조항", "책임 범위"],
        "departments": ["법무팀"],
        "summary_generalized": "표준 계약 조항과 책임 범위·데이터 처리 관련 법무 검토가 진행 중.",
        "entities": [
            {"text": "99.5퍼센트", "type": "수치"},
            {"text": "4영업시간", "type": "수치"},
        ],
    },
    "enterprise_contract_negotiation#4": {
        "security_level": 3,
        "keywords": ["협상 리스크", "가격 압박", "매출 인식"],
        "departments": ["영업팀"],
        "summary_generalized": "일부 건은 가격 압박·일정 지연 등 협상 리스크가 있음.",
        "entities": [
            {"text": "넥스가드", "type": "경쟁사"},
            {"text": "한빛전자", "type": "고객사"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "대한모빌리티", "type": "고객사"},
        ],
    },
    # ── 인력 보상·리텐션 (D1 일반 / D4 인사기밀) ──
    "hr_compensation_retention_plan#0": {
        "security_level": 1,
        "keywords": ["조직 운영", "인력 현황"],
        "departments": ["인사팀"],
        "summary_generalized": "사업부 조직 구성과 인력 운영 현황.",
        "entities": [{"text": "31명", "type": "수치"}],
    },
    "hr_compensation_retention_plan#1": {
        "security_level": 1,
        "keywords": ["채용 계획", "직무"],
        "departments": ["인사팀"],
        "summary_generalized": "직군별 채용 계획과 우대 경험.",
        "entities": [],
    },
    "hr_compensation_retention_plan#2": {
        "security_level": 4,
        "keywords": ["성과 평가", "인사 평가"],
        "departments": ["인사팀", "경영진"],
        "summary_generalized": "핵심 인력에 대한 개인별 성과 평가 내용이 존재함(내용 비공개).",
        "entities": [
            {"text": "강도현", "type": "인명"},
            {"text": "박지윤", "type": "인명"},
            {"text": "이서아", "type": "인명"},
            {"text": "세림은행", "type": "고객사"},
            {"text": "한빛전자", "type": "고객사"},
            {"text": "대한모빌리티", "type": "고객사"},
        ],
    },
    "hr_compensation_retention_plan#3": {
        "security_level": 4,
        "keywords": ["특별 보상", "인센티브"],
        "departments": ["인사팀", "경영진"],
        "summary_generalized": "핵심 인력 대상 특별 보상안이 검토 중임(대상·금액 비공개).",
        "entities": [
            {"text": "강도현", "type": "인명"},
            {"text": "박지윤", "type": "인명"},
            {"text": "이서아", "type": "인명"},
            {"text": "1.8억", "type": "금액"},
        ],
    },
    "hr_compensation_retention_plan#4": {
        "security_level": 4,
        "keywords": ["퇴사 리스크", "리텐션"],
        "departments": ["인사팀", "경영진"],
        "summary_generalized": "일부 핵심 인력의 이탈 리스크와 대응 방안이 관리되고 있음(개인정보 비공개).",
        "entities": [
            {"text": "강도현", "type": "인명"},
            {"text": "박지윤", "type": "인명"},
            {"text": "35퍼센트", "type": "수치"},
            {"text": "2개월", "type": "수치"},
        ],
    },
    # ── 보안 점검·사고 대응 (D1/D2/D3) ──
    "security_incident_review#0": {
        "security_level": 1,
        "keywords": ["보안 점검", "감사"],
        "departments": ["보안팀", "개발팀"],
        "summary_generalized": "외부 공유 링크·권한·로그에 대한 사전 보안 점검 개요.",
        "entities": [],
    },
    "security_incident_review#1": {
        "security_level": 2,
        "keywords": ["발견 사항", "취약점"],
        "departments": ["보안팀", "개발팀"],
        "summary_generalized": "일부 정책 적용·로그 기록 관련 개선 필요 사항이 발견됨.",
        "entities": [{"text": "3건", "type": "수치"}],
    },
    "security_incident_review#2": {
        "security_level": 3,
        "keywords": ["재현 경로", "제한 정보", "토큰"],
        "departments": ["보안팀"],
        "summary_generalized": "문제 재현 절차와 제한된 테스트 식별자가 포함됨(상세 비공개).",
        "entities": [
            {"text": "tmp_share_7f92_redacted_demo", "type": "토큰"},
            {"text": "req-20260709-demo-1842", "type": "식별자"},
            {"text": "14일", "type": "수치"},
            {"text": "3일", "type": "수치"},
        ],
    },
    "security_incident_review#3": {
        "security_level": 2,
        "keywords": ["영향도 평가", "노출 여부"],
        "departments": ["보안팀"],
        "summary_generalized": "비공개 원문 외부 노출은 없었으나 일부 정책·감사 품질 개선이 필요.",
        "entities": [],
    },
    "security_incident_review#4": {
        "security_level": 2,
        "keywords": ["조치 계획", "개선"],
        "departments": ["개발팀", "보안팀"],
        "summary_generalized": "링크 검증·변경 사유 필수화·정책 시뮬레이션 등 조치 계획.",
        "entities": [],
    },
}


def split_semantic_sections(md_path: Path) -> tuple[str, list[dict]]:
    """마크다운 원문을 문단/의미 단위 보안 객체로 분리한다.

    - `##` heading은 등급 시드의 parent 단위로 보존한다.
    - 빈 줄로 나뉜 문단 하나를 독립적인 `sections` row로 저장한다.
    - 너무 짧은 라인 단위가 아니라 문단 단위라 검색/LLM 컨텍스트에서 의미가 유지된다.
    """
    doc_title = md_path.stem
    chunks: list[dict] = []
    heading_title: str | None = None
    heading_idx = -1
    paragraph_idx_in_heading = 0
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines, paragraph_idx_in_heading
        if heading_title is None:
            paragraph_lines = []
            return
        text = "\n".join(line.strip() for line in paragraph_lines).strip()
        paragraph_lines = []
        if not text:
            return

        chunk_idx = len(chunks)
        paragraph_idx_in_heading += 1
        source_section_id = f"{md_path.stem}#{heading_idx}"
        chunks.append({
            "id": f"{md_path.stem}#{chunk_idx}",
            "doc": md_path.stem,
            "doc_title": doc_title,
            "seq": chunk_idx,
            "title": f"{heading_title} · 문단 {paragraph_idx_in_heading}",
            "parent_title": heading_title,
            "source_section_id": source_section_id,
            "text": text,
        })

    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("# ") and not line.startswith("## "):
            doc_title = line[2:].strip()
            continue
        if line.startswith("## "):
            flush_paragraph()
            heading_idx += 1
            paragraph_idx_in_heading = 0
            heading_title = line[3:].strip()
            continue
        if not line.strip():
            flush_paragraph()
            continue
        paragraph_lines.append(line)
    flush_paragraph()

    for chunk in chunks:
        chunk["doc_title"] = doc_title
    return doc_title, chunks


def _entities_in_text(entities: list[dict], text: str) -> list[dict]:
    return [dict(e) for e in entities if e["text"] in text]


def build_sections() -> tuple[list[dict], list[str]]:
    """samples 파싱 → GRADES 병합 → 플레이스홀더 부여. (sections, 미매칭 id 목록) 반환.

    반환 dict는 엔진이 기대하는 표준 섹션 스키마(store.py 참조)를 가지며, 각 항목은
    문단/의미 단위 보안 객체다. `source_section_id`로 사람이 검수한 heading 단위 등급 시드를 참조한다.
    """
    all_sections: list[dict] = []
    for md_path in sorted(SAMPLES_DIR.glob("*.md")):
        if md_path.stem == "README":
            continue
        _, sections = split_semantic_sections(md_path)
        all_sections.extend(sections)

    missing: list[str] = []
    for s in all_sections:
        g = GRADES.get(s["source_section_id"])
        if g is None:
            # default-deny: 등급 시드가 없으면 D4로 격리하고 검수 대상 표시
            missing.append(s["source_section_id"])
            s.update(
                security_level=4,
                confidence=0.0,
                keywords=[],
                departments=[],
                summary_generalized="(미분류 — 관리자 검수 필요)",
                entities=[],
                needs_review=True,
            )
            continue
        conf = g.get("confidence", DEFAULT_CONFIDENCE)
        entities = _entities_in_text(g.get("entities", []), s["text"])
        s.update(
            security_level=g["security_level"],
            confidence=conf,
            keywords=list(g.get("keywords", [])),
            departments=list(g.get("departments", [])),
            summary_generalized=g.get("summary_generalized", ""),
            entities=entities,
        )
        s["needs_review"] = conf < 0.8 or g["security_level"] >= 3

    assign_placeholders(all_sections)
    return all_sections, sorted(set(missing))


def seed(db_path: str | Path = DB_PATH) -> dict:
    """samples를 파싱·병합해 SQLite에 직접 INSERT한다. 요약 통계를 반환."""
    sections, missing = build_sections()

    conn = get_conn(db_path)
    try:
        init_db(conn, reset=True)

        # documents (doc 단위 dedup)
        docs: dict[str, str] = {}
        for s in sections:
            docs.setdefault(s["doc"], s["doc_title"])
        conn.executemany(
            "INSERT INTO documents(doc, doc_title, source_path) VALUES (?,?,?)",
            [(doc, title, f"data/samples/{doc}.md") for doc, title in docs.items()],
        )

        # sections
        conn.executemany(
            """INSERT INTO sections
               (id, doc, seq, title, parent_title, source_section_id, text, security_level, confidence,
                needs_review, keywords, departments, summary_generalized)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    s["id"], s["doc"], s["seq"], s["title"], s["parent_title"],
                    s["source_section_id"], s["text"],
                    s["security_level"], s["confidence"], 1 if s["needs_review"] else 0,
                    json.dumps(s["keywords"], ensure_ascii=False),
                    json.dumps(s["departments"], ensure_ascii=False),
                    s["summary_generalized"],
                )
                for s in sections
            ],
        )

        # entities (섹션 내 순서 보존)
        conn.executemany(
            "INSERT INTO entities(section_id, seq, text, placeholder, type) VALUES (?,?,?,?,?)",
            [
                (s["id"], i, e["text"], e["placeholder"], e.get("type"))
                for s in sections
                for i, e in enumerate(s["entities"])
            ],
        )

        # personas
        conn.executemany(
            "INSERT INTO personas(id, name, clearance, department, channel) VALUES (?,?,?,?,?)",
            [(p["id"], p["name"], p["clearance"], p["department"], p["channel"]) for p in PERSONAS],
        )
        conn.commit()

        stats = {
            "documents": conn.execute("SELECT count(*) FROM documents").fetchone()[0],
            "sections": conn.execute("SELECT count(*) FROM sections").fetchone()[0],
            "entities": conn.execute("SELECT count(*) FROM entities").fetchone()[0],
            "personas": conn.execute("SELECT count(*) FROM personas").fetchone()[0],
            "missing": missing,
        }
        return stats
    finally:
        conn.close()


def report() -> int:
    """A1 검증용: 등급 병합 결과와 미매칭 섹션을 출력한다 (DB 미생성)."""
    sections, missing = build_sections()
    grade_keys = {k for k in GRADES}
    parsed_source_ids = {s["source_section_id"] for s in sections}
    orphan = sorted(grade_keys - parsed_source_ids)  # GRADES에만 있고 실제 heading엔 없는 id

    print(f"문서 {len({s['doc'] for s in sections})}개 · 섹션 {len(sections)}개\n")
    by_level: dict[int, int] = {}
    for s in sections:
        lvl = s["security_level"]
        by_level[lvl] = by_level.get(lvl, 0) + 1
        ents = ",".join(f"{e['text']}→{e['placeholder']}" for e in s["entities"]) or "-"
        review = " ⚠검수" if s["needs_review"] else ""
        print(f"  D{lvl} {s['id']:42s} {s['title']} ({s['source_section_id']}){review}")
        print(f"       부서={s['departments']} 키워드={s['keywords']}")
        print(f"       요약={s['summary_generalized']}")
        print(f"       엔티티={ents}\n")

    print("등급 분포:", {f"D{k}": by_level[k] for k in sorted(by_level)})
    if missing:
        print(f"\n⚠ GRADES 미지정(→D4 격리) 섹션 {len(missing)}개: {missing}", file=sys.stderr)
    if orphan:
        print(f"⚠ 실제 섹션에 없는 GRADES 키 {len(orphan)}개(id 오타?): {orphan}", file=sys.stderr)
    if not missing and not orphan:
        print("\n✅ 모든 섹션이 GRADES와 정확히 일치 (미매칭 0건)")
    return 1 if (missing or orphan) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="samples 등급 시드 검증 도구")
    parser.add_argument("--report", action="store_true", help="등급 병합 결과·미매칭 점검 (DB 미생성)")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="사용 중단: 샘플 초기화는 `python -m app.init_samples --reset`을 사용",
    )
    args = parser.parse_args()

    if args.report:
        raise SystemExit(report())

    if args.reset:
        print(
            "samples 초기화는 명시적 초기화 명령에서만 실행됩니다:\n"
            "  python -m app.init_samples --reset",
            file=sys.stderr,
        )
        raise SystemExit(2)

    parser.print_help()
    print(
        "\nDB 쓰기 작업은 수행하지 않았습니다. samples를 DB에 넣으려면 "
        "`python -m app.init_samples --reset`을 실행하세요."
    )


if __name__ == "__main__":
    main()
