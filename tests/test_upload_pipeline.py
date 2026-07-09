#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store, upload_pipeline
from app.seed_db import seed


def _label(section_id: str | None = None, entities=None, level: int = 3) -> dict:
    payload = {
        "security_level": level,
        "confidence": 0.91,
        "keywords": ["계약 금액", "고객사"],
        "departments": ["영업팀"],
        "summary_generalized": "고객 계약 조건과 금액 정보가 포함된 기밀 문단.",
        "entities": entities if entities is not None
        else [{"text": "한빛전자", "type": "고객사"}, {"text": "12억", "type": "금액"}],
    }
    if section_id is not None:
        payload["id"] = section_id
    return payload


class FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload, ensure_ascii=False)
        self.parsed = None


class FakeModels:
    """배치 프롬프트(<section id=...>)면 배열을, 문단별 프롬프트면 단일 객체를 반환."""

    def __init__(self, entities=None, drop_ids: set[str] | None = None):
        self.calls = []
        self.entities = entities
        self.drop_ids = drop_ids or set()

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["contents"]
        ids = re.findall(r'<section id="([^"]+)"', prompt)
        if ids:  # 배치 호출
            return FakeResponse([
                _label(i, entities=self.entities) for i in ids if i not in self.drop_ids
            ])
        return FakeResponse(_label(entities=self.entities))


class FakeGemini:
    def __init__(self, entities=None, drop_ids: set[str] | None = None):
        self.models = FakeModels(entities=entities, drop_ids=drop_ids)


def check(label: str, condition: bool) -> None:
    if not condition:
        print(f"[FAIL] {label}")
        raise SystemExit(1)
    print(f"[OK ] {label}")


CONTRACT_DOC = (
    "# 업로드 계약 메모\n\n"
    "## 계약 조건\n한빛전자 제안 금액은 12억이며 할인 조건은 비공개입니다.\n\n"
    "## 일정\n한빛전자 계약 체결 목표는 12억 규모로 다음 분기입니다."
)


def main() -> None:
    # ── 배치 1회 호출: 문단 2개 문서가 Gemini 호출 1번으로 분류·저장 ──
    seed()
    fake = FakeGemini()
    result = upload_pipeline.classify_and_store("uploaded_contract.md", CONTRACT_DOC, client=fake)
    sections = store.sections_for_doc(result["doc"])

    check("문서 전체가 Gemini 1회 호출로 분류됨", len(fake.models.calls) == 1)
    check("업로드 문서가 DB에 저장됨", result["doc"] == "uploaded_contract" and len(sections) == 2)
    check("분류 등급이 섹션에 저장됨", all(s["security_level"] == 3 for s in sections))
    check("엔티티 플레이스홀더가 저장됨", {e["text"] for e in sections[0]["entities"]} == {"한빛전자", "12억"})
    check("검수 대상 플래그가 저장됨", sections[0]["needs_review"] is True)

    # ── 폴백: 배치 응답에서 누락된 섹션만 문단별 호출로 재분류 ──
    seed()
    partial = FakeGemini(drop_ids={"uploaded_contract#1"})
    partial_result = upload_pipeline.classify_and_store("uploaded_contract.md", CONTRACT_DOC, client=partial)
    partial_sections = store.sections_for_doc(partial_result["doc"])
    check("배치 누락 시 해당 섹션만 폴백 호출 (총 2회)", len(partial.models.calls) == 2)
    check("폴백 포함 전체 섹션이 저장됨", len(partial_sections) == 2)
    check("폴백 섹션도 등급이 저장됨", partial_sections[1]["security_level"] == 3)

    # ── 문자열 엔티티 응답 정규화 (배치 경로) ──
    seed()
    string_entity_fake = FakeGemini(entities=["DataKeeper", "2027년", "35퍼센트"])
    string_result = upload_pipeline.classify_and_store(
        "uploaded_strategy.md",
        "# 업로드 전략 메모\n\n## 성장 계획\nDataKeeper는 2027년까지 전환율을 35퍼센트로 높이는 계획을 검토합니다.",
        client=string_entity_fake,
    )
    string_sections = store.sections_for_doc(string_result["doc"])
    check("문자열 엔티티 응답도 정규화됨", {e["text"] for e in string_sections[0]["entities"]} == {"DataKeeper", "2027년", "35퍼센트"})
    check("문자열 엔티티에 타입이 부여됨", all(e["type"] for e in string_sections[0]["entities"]))

    print("\n업로드 파이프라인 테스트 통과 ✅")


if __name__ == "__main__":
    main()
