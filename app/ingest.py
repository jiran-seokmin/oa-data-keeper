"""수집 파이프라인: 시드 문서 → 섹션 분리 → 분류 → data/sections.json

두 가지 모드:
  python -m app.ingest --offline   # data/labels.json의 사전 분류 라벨 사용 (API 불필요)
  python -m app.ingest             # Claude로 라이브 분류 (ANTHROPIC_API_KEY 필요)

데모 원칙: 분류 결과(sections.json)는 커밋해서 고정한다. 데모 중 라이브 LLM 호출은
답변 생성 하나로 제한하고, 수집은 사전에 1회 실행한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data" / "seed"
LABELS_PATH = ROOT / "data" / "labels.json"
OUT_PATH = ROOT / "data" / "sections.json"
KEYWORDS_PATH = ROOT / "app" / "keywords.yaml"

MODEL = os.environ.get("ACE_MODEL", "claude-opus-4-8")


def split_sections(md_path: Path) -> tuple[str, list[dict]]:
    """'# ' 제목 + '## ' 섹션 구조의 마크다운을 섹션 단위로 분리."""
    doc_title = md_path.stem
    sections: list[dict] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush():
        if current_title is not None:
            body = "\n".join(current_lines).strip()
            sections.append({"title": current_title, "text": body})

    for line in md_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            doc_title = line[2:].strip()
        elif line.startswith("## "):
            flush()
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()

    for i, s in enumerate(sections):
        s["id"] = f"{md_path.stem}#{i}"
        s["doc"] = md_path.stem
        s["doc_title"] = doc_title
    return doc_title, sections


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


def classify_offline(sections: list[dict]) -> None:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    missing = []
    for s in sections:
        label = labels.get(s["id"])
        if label is None:
            # default-deny: 라벨이 없으면 D4로 격리하고 검수 대상으로 표시
            missing.append(s["id"])
            s.update(security_level=4, confidence=0.0, keywords=[], departments=[],
                     summary_generalized="(미분류 — 관리자 검수 필요)", entities=[],
                     needs_review=True)
        else:
            s.update(label)
            s["needs_review"] = label["confidence"] < 0.8 or label["security_level"] >= 3
    if missing:
        print(f"경고: 라벨 없는 섹션 {len(missing)}개 → D4 격리: {missing}", file=sys.stderr)


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


def classify_live(sections: list[dict]) -> None:
    import anthropic
    from pydantic import BaseModel, Field

    class Entity(BaseModel):
        text: str
        type: str = Field(description="고객사/인물/금액/수치/조건/코드네임/경쟁사 등")

    class SectionLabel(BaseModel):
        security_level: int = Field(ge=0, le=4)
        confidence: float = Field(ge=0, le=1)
        keywords: list[str]
        departments: list[str]
        summary_generalized: str
        entities: list[Entity]

    hints = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8"))["hints"]
    hints_text = "\n".join(f"- '{h['keyword']}' → D{h['level']}" for h in hints)
    system = CLASSIFY_SYSTEM.format(hints=hints_text)

    client = anthropic.Anthropic()
    for s in sections:
        prompt = f"문서: {s['doc_title']}\n섹션 제목: {s['title']}\n\n{s['text']}"
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=SectionLabel,
        )
        label = response.parsed_output
        s.update(label.model_dump())
        s["needs_review"] = label.confidence < 0.8 or label.security_level >= 3
        print(f"  {s['id']}: D{label.security_level} (conf {label.confidence:.2f}) — {s['title']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="시드 문서 수집·분류 파이프라인")
    parser.add_argument("--offline", action="store_true",
                        help="data/labels.json의 사전 분류 라벨 사용 (API 호출 없음)")
    args = parser.parse_args()

    all_sections: list[dict] = []
    for md_path in sorted(SEED_DIR.glob("*.md")):
        _, sections = split_sections(md_path)
        all_sections.extend(sections)
    print(f"문서 {len(list(SEED_DIR.glob('*.md')))}개 → 섹션 {len(all_sections)}개")

    if args.offline:
        classify_offline(all_sections)
    else:
        classify_live(all_sections)

    assign_placeholders(all_sections)

    OUT_PATH.write_text(json.dumps(all_sections, ensure_ascii=False, indent=2), encoding="utf-8")
    review = [s["id"] for s in all_sections if s.get("needs_review")]
    print(f"저장: {OUT_PATH} (검수 대상 {len(review)}개 섹션)")


if __name__ == "__main__":
    main()
