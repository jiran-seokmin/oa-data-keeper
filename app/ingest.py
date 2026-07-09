"""분류 공용 자산: 분류 프롬프트 + 엔티티 플레이스홀더 부여.

과거 seed 코퍼스 수집 CLI(`python -m app.ingest`)는 DB 직접 시딩(`app/seed_db.py`)으로
대체되어 제거됐다. 이 모듈은 시딩·런타임 업로드 분류가 공유하는 자산만 남긴다:

- `CLASSIFY_SYSTEM` / `KEYWORDS_PATH` — 업로드 문서 분류 프롬프트 (`app/upload_pipeline.py`)
- `assign_placeholders` — 코퍼스 전역 엔티티 플레이스홀더 (`app/seed_db.py`, `app/upload_pipeline.py`)
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYWORDS_PATH = ROOT / "app" / "keywords.yaml"


def assign_placeholders(sections: list[dict]) -> None:
    """엔티티에 타입별 플레이스홀더 부여. 코퍼스 전체에서 같은 엔티티는 같은 플레이스홀더."""
    assigned: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    for s in sections:
        for e in s.get("entities", []):
            key = (e["type"], e["text"])
            if key not in assigned:
                n = counters.get(e["type"], 0)
                counters[e["type"]] = n + 1
                suffix = chr(ord("A") + n) if n < 26 else str(n)
                assigned[key] = f"[{e['type']}{suffix}]"
            e["placeholder"] = assigned[key]


CLASSIFY_SYSTEM = """당신은 사내 문서의 데이터 보안 등급 분류기입니다.

보안 등급 기준:
- 0 (D0 외부 정보): 공개해도 되는 정보 (보도자료, 공개 제품 소개)
- 1 (D1 일반 정보): 사내 일반 공유 정보 (공지, 일반 회의록)
- 2 (D2 제한 접근): 부서 업무 정보 (영업 파이프라인, 미팅 노트)
- 3 (D3 기밀 접근): 계약 조건, 금액, 매출 등 기밀
- 4 (D4 최고 접근): M&A, 인사 평가, 미공개 재무, 투자 유치

관리자 등록 키워드 힌트:
{hints}

섹션을 분석해 다음을 반환하세요:
- security_level: 위 기준의 등급 (경계가 애매하면 높은 쪽 — default-deny)
- confidence: 분류 확신도 0~1
- keywords: 등급 판단 근거 키워드
- departments: 이 데이터의 담당 부서 목록 (영업팀/개발팀/재무팀/인사팀/경영진 중)
- summary_generalized: A2(의미 제한)용 일반화 요약 한 문장 — 고유명사 제거, 수치는 규모/범위로, 조건은 카테고리로
- entities: 마스킹 대상 엔티티 (고객사명, 인명, 금액, 민감 수치, 코드네임 등)"""
