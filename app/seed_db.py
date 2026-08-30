"""Deterministic sample seeding for the C/S/O classification model.

Static labels are reviewed seed data and therefore enter the database as
``user_confirmed``.  A parsed heading without a matching label keeps ``grade``
as ``None`` and enters ``pending_review``; the access core treats that state as
default-deny.  The intentionally deleted AI sales sample is not restored and
has no orphan label entries here.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from app import store
from app.db import DB_PATH, get_conn, init_db
from app.engine import document_grade

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "data" / "samples"

DEFAULT_CONFIDENCE = 0.95
SEED_CONFIRMED_AT = "2026-08-30T00:00:00+09:00"


# Existing demo identities mapped to the new three-grade access model.
PERSONAS = [
    {"id": "external", "name": "외부 고객", "access_grade": "O", "department": None, "channel": "external"},
    {"id": "junior_dev", "name": "신입 개발자", "access_grade": "S", "department": "개발팀", "channel": "internal"},
    {"id": "sales_rep", "name": "영업팀원", "access_grade": "S", "department": "영업팀", "channel": "internal"},
    {"id": "sales_lead", "name": "영업팀장", "access_grade": "S", "department": "영업팀", "channel": "internal"},
    {"id": "ceo", "name": "CEO", "access_grade": "C", "department": "경영진", "channel": "internal"},
]


# Reviewed heading-level labels. Exact legacy mapping: D0 -> O, D1-D3 -> S, D4 -> C.
# Child paragraphs inherit the label through source_section_id.
GRADES: dict[str, dict] = {
    "enterprise_contract_negotiation#0": {
        "grade": "S",
        "keywords": ["계약 개요", "우선 협상 고객"],
        "departments": ["영업팀"],
        "summary": "복수의 우선 협상 고객이 있으며 도입 목적과 보안 요구가 상이함.",
    },
    "enterprise_contract_negotiation#1": {
        "grade": "S",
        "keywords": ["고객 요구사항", "보안 요구"],
        "departments": ["영업팀"],
        "summary": "고객별로 협력사 공유·권한 분리·망분리 등 서로 다른 보안 요구를 제시.",
    },
    "enterprise_contract_negotiation#2": {
        "grade": "S",
        "keywords": ["제안 금액", "할인 조건", "보상 한도"],
        "departments": ["영업팀", "재무팀"],
        "summary": "대형 건별 제안 금액과 할인·보상 조건을 협상 중.",
    },
    "enterprise_contract_negotiation#3": {
        "grade": "S",
        "keywords": ["법무 검토", "계약 조항", "책임 범위"],
        "departments": ["법무팀"],
        "summary": "표준 계약 조항과 책임 범위·데이터 처리 관련 법무 검토가 진행 중.",
    },
    "enterprise_contract_negotiation#4": {
        "grade": "S",
        "keywords": ["협상 리스크", "가격 압박", "매출 인식"],
        "departments": ["영업팀"],
        "summary": "일부 건은 가격 압박·일정 지연 등 협상 리스크가 있음.",
    },
    "hr_compensation_retention_plan#0": {
        "grade": "S",
        "keywords": ["조직 운영", "인력 현황"],
        "departments": ["인사팀"],
        "summary": "사업부 조직 구성과 인력 운영 현황.",
    },
    "hr_compensation_retention_plan#1": {
        "grade": "S",
        "keywords": ["채용 계획", "직무"],
        "departments": ["인사팀"],
        "summary": "직군별 채용 계획과 우대 경험.",
    },
    "hr_compensation_retention_plan#2": {
        "grade": "C",
        "keywords": ["성과 평가", "인사 평가"],
        "departments": ["인사팀", "경영진"],
        "summary": "핵심 인력에 대한 개인별 성과 평가 내용.",
    },
    "hr_compensation_retention_plan#3": {
        "grade": "C",
        "keywords": ["특별 보상", "인센티브"],
        "departments": ["인사팀", "경영진"],
        "summary": "핵심 인력 대상 특별 보상안이 검토 중임.",
    },
    "hr_compensation_retention_plan#4": {
        "grade": "C",
        "keywords": ["퇴사 리스크", "리텐션"],
        "departments": ["인사팀", "경영진"],
        "summary": "일부 핵심 인력의 이탈 리스크와 대응 방안이 관리되고 있음.",
    },
    "security_incident_review#0": {
        "grade": "S",
        "keywords": ["보안 점검", "감사"],
        "departments": ["보안팀", "개발팀"],
        "summary": "외부 공유 링크·권한·로그에 대한 사전 보안 점검 개요.",
    },
    "security_incident_review#1": {
        "grade": "S",
        "keywords": ["발견 사항", "취약점"],
        "departments": ["보안팀", "개발팀"],
        "summary": "일부 정책 적용·로그 기록 관련 개선 필요 사항이 발견됨.",
    },
    "security_incident_review#2": {
        "grade": "S",
        "keywords": ["재현 경로", "제한 정보", "토큰"],
        "departments": ["보안팀"],
        "summary": "문제 재현 절차와 제한된 테스트 식별자가 포함됨.",
    },
    "security_incident_review#3": {
        "grade": "S",
        "keywords": ["영향도 평가", "노출 여부"],
        "departments": ["보안팀"],
        "summary": "비공개 원문 외부 노출은 없었으나 일부 정책·감사 품질 개선이 필요.",
    },
    "security_incident_review#4": {
        "grade": "S",
        "keywords": ["조치 계획", "개선"],
        "departments": ["개발팀", "보안팀"],
        "summary": "링크 검증·변경 사유 필수화·정책 시뮬레이션 등 조치 계획.",
    },
}


def split_semantic_sections(md_path: Path) -> tuple[str, list[dict]]:
    """Split Markdown into paragraph-level objects while preserving heading IDs."""

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
        chunks.append(
            {
                "id": f"{md_path.stem}#{chunk_idx}",
                "doc": md_path.stem,
                "doc_title": doc_title,
                "seq": chunk_idx,
                "title": f"{heading_title} · 문단 {paragraph_idx_in_heading}",
                "parent_title": heading_title,
                "source_section_id": source_section_id,
                "text": text,
            }
        )

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


def _static_reason(label: dict) -> str:
    evidence = ", ".join(label.get("keywords", [])) or "사람 검토"
    return f"사람이 검토한 정적 시드 기준: {evidence}"


def build_sections() -> tuple[list[dict], list[str]]:
    """Parse samples and merge reviewed C/S/O labels without any runtime LLM call."""

    all_sections: list[dict] = []
    for md_path in sorted(SAMPLES_DIR.glob("*.md")):
        if md_path.stem == "README":
            continue
        _, sections = split_semantic_sections(md_path)
        all_sections.extend(sections)

    missing: list[str] = []
    for section in all_sections:
        label = GRADES.get(section["source_section_id"])
        if label is None:
            missing.append(section["source_section_id"])
            section.update(
                grade=None,
                confidence=0.0,
                keywords=[],
                departments=[],
                summary="(미분류 - 사용자 검수 필요)",
                classification_reason="정적 등급 시드가 없어 자동 접근을 차단함",
                classification_status="pending_review",
                confirmed_by=None,
                confirmed_at=None,
            )
            continue

        section.update(
            grade=label["grade"],
            confidence=float(label.get("confidence", DEFAULT_CONFIDENCE)),
            keywords=list(label.get("keywords", [])),
            departments=list(label.get("departments", [])),
            summary=label.get("summary", ""),
            classification_reason=label.get("classification_reason") or _static_reason(label),
            classification_status="user_confirmed",
            confirmed_by="seed-reviewer",
            confirmed_at=SEED_CONFIRMED_AT,
        )
    return all_sections, sorted(set(missing))


def seed(
    db_path: str | Path = DB_PATH,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Reset and seed the sample database, returning deterministic statistics."""

    sections, missing = build_sections()
    own_connection = conn is None
    conn = conn or get_conn(db_path)
    try:
        init_db(conn, reset=True)

        documents: dict[str, dict] = {}
        for section in sections:
            documents.setdefault(
                section["doc"],
                {
                    "doc": section["doc"],
                    "doc_title": section["doc_title"],
                    "source_path": f"data/samples/{section['doc']}.md",
                },
            )
        for document in documents.values():
            store.upsert_document(document, conn=conn)
        store.upsert_sections(sections, conn=conn)

        for section in sections:
            pending = section["classification_status"] == "pending_review"
            store.record_classification_event(
                section["id"],
                "classification_pending" if pending else "user_confirmed",
                actor="system" if pending else "seed-reviewer",
                new_grade=section["grade"],
                new_status=section["classification_status"],
                reason=section["classification_reason"],
                confidence=section["confidence"],
                conn=conn,
            )

        for persona in PERSONAS:
            store.upsert_persona(persona, conn=conn)
        if own_connection:
            conn.commit()

        document_grades = {
            doc: document_grade([section for section in sections if section["doc"] == doc])
            for doc in documents
        }
        return {
            "documents": len(documents),
            "sections": len(sections),
            "personas": len(PERSONAS),
            "classification_events": len(sections),
            "pending_review": sum(
                1 for section in sections if section["classification_status"] == "pending_review"
            ),
            "document_grades": document_grades,
            "missing": missing,
        }
    except Exception:
        if own_connection:
            conn.rollback()
        raise
    finally:
        if own_connection:
            conn.close()


def report() -> int:
    """Print C/S/O seed coverage without creating a database."""

    sections, missing = build_sections()
    parsed_source_ids = {section["source_section_id"] for section in sections}
    orphan = sorted(set(GRADES) - parsed_source_ids)

    print(f"문서 {len({section['doc'] for section in sections})}개 · 섹션 {len(sections)}개\n")
    by_grade: dict[str, int] = {}
    for section in sections:
        grade = section["grade"] or "미분류"
        by_grade[grade] = by_grade.get(grade, 0) + 1
        review = " 검수대기" if section["classification_status"] == "pending_review" else ""
        print(
            f"  {grade:4s} {section['id']:42s} {section['title']} "
            f"({section['source_section_id']}) [{section['classification_status']}]{review}"
        )
        print(f"       부서={section['departments']} 키워드={section['keywords']}")
        print(f"       요약={section['summary']}")
        print(f"       근거={section['classification_reason']}\n")

    print("등급 분포:", {grade: by_grade[grade] for grade in sorted(by_grade)})
    if missing:
        print(f"\nGRADES 미지정(검수 대기) 섹션 {len(missing)}개: {missing}", file=sys.stderr)
    if orphan:
        print(f"실제 섹션에 없는 GRADES 키 {len(orphan)}개: {orphan}", file=sys.stderr)
    if not missing and not orphan:
        print("\n모든 섹션이 C/S/O 정적 시드와 정확히 일치 (미매칭 0건)")
    return 1 if (missing or orphan) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="samples C/S/O 등급 시드 검증 도구")
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
