#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store, upload_pipeline
from app.seed_db import seed


class FakeResponse:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload, ensure_ascii=False)


class FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse({
            "security_level": 3,
            "confidence": 0.91,
            "keywords": ["계약 금액", "고객사"],
            "departments": ["영업팀"],
            "summary_generalized": "고객 계약 조건과 금액 정보가 포함된 기밀 문단.",
            "entities": [{"text": "한빛전자", "type": "고객사"}, {"text": "12억", "type": "금액"}],
        })


class FakeGemini:
    def __init__(self):
        self.models = FakeModels()


def check(label: str, condition: bool) -> None:
    if not condition:
        print(f"[FAIL] {label}")
        raise SystemExit(1)
    print(f"[OK ] {label}")


def main() -> None:
    seed()
    fake = FakeGemini()
    result = upload_pipeline.classify_and_store(
        "uploaded_contract.md",
        "# 업로드 계약 메모\n\n## 계약 조건\n한빛전자 제안 금액은 12억이며 할인 조건은 비공개입니다.",
        client=fake,
    )
    sections = store.sections_for_doc(result["doc"])

    check("Gemini 분류가 섹션 단위로 호출됨", len(fake.models.calls) == 1)
    check("업로드 문서가 DB에 저장됨", result["doc"] == "uploaded_contract" and len(sections) == 1)
    check("분류 등급이 섹션에 저장됨", sections[0]["security_level"] == 3)
    check("엔티티 플레이스홀더가 저장됨", {e["text"] for e in sections[0]["entities"]} == {"한빛전자", "12억"})
    check("검수 대상 플래그가 저장됨", sections[0]["needs_review"] is True)

    print("\n업로드 파이프라인 테스트 통과 ✅")


if __name__ == "__main__":
    main()
