"""C/S/O upload classification, review state and Skill injection tests."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store, upload_pipeline
from app.config import classification_model, has_gemini_credentials
from app.db import get_conn


def _label(
    section_id: str | None = None,
    *,
    grade: str = "S",
    confidence: float = 0.91,
    applied_skills: list[str] | None = None,
) -> dict:
    payload = {
        "grade": grade,
        "confidence": confidence,
        "keywords": ["계약 금액", "고객사"],
        "departments": ["영업팀"],
        "summary": "고객 계약 조건과 금액 정보가 포함된 내부 문단.",
        "classification_reason": "가격과 계약 조건이 포함되어 민감 등급으로 분류",
        "applied_skills": applied_skills or [],
    }
    if section_id is not None:
        payload["id"] = section_id
    return payload


class FakeResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload, ensure_ascii=False)
        self.parsed = None


class FakeModels:
    def __init__(
        self,
        *,
        drop_ids: set[str] | None = None,
        grade: str = "S",
        confidence: float = 0.91,
        applied_skills: list[str] | None = None,
    ):
        self.calls: list[dict] = []
        self.drop_ids = drop_ids or set()
        self.grade = grade
        self.confidence = confidence
        self.applied_skills = applied_skills or []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        ids = re.findall(r'<section id="([^"]+)"', kwargs["contents"])
        if ids:
            return FakeResponse(
                [
                    _label(
                        section_id,
                        grade=self.grade,
                        confidence=self.confidence,
                        applied_skills=self.applied_skills,
                    )
                    for section_id in ids
                    if section_id not in self.drop_ids
                ]
            )
        return FakeResponse(
            _label(
                grade=self.grade,
                confidence=self.confidence,
                applied_skills=self.applied_skills,
            )
        )


class FakeGemini:
    def __init__(self, **kwargs):
        self.models = FakeModels(**kwargs)


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


CONTRACT_DOC = (
    "# 업로드 계약 메모\n\n"
    "## 계약 조건\n한빛전자 제안 금액은 12억이며 할인 조건은 비공개입니다.\n\n"
    "## 일정\n한빛전자 계약 체결 목표는 12억 규모로 다음 분기입니다."
)


def main() -> None:
    with patch.dict(
        os.environ,
        {
            "ACE_PROVIDER": "anthropic",
            "ACE_MODEL": "claude-opus-4-8",
            "GEMINI_API_KEY": "test-key",
        },
        clear=True,
    ):
        check("챗이 Anthropic이어도 업로드는 Gemini 모델 사용", (
            has_gemini_credentials() and classification_model() == "gemini-2.5-flash"
        ))

    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "upload-test.db"

        fake = FakeGemini()
        result = upload_pipeline.classify_and_store(
            "uploaded_contract.md",
            CONTRACT_DOC,
            client=fake,
            db_path=db_path,
        )
        conn = get_conn(db_path)
        try:
            sections = store.sections_for_doc(result["doc"], conn)
            logs = store.load_classification_logs(conn, doc=result["doc"])
        finally:
            conn.close()
        check("문서 전체를 Gemini 1회로 분류", len(fake.models.calls) == 1)
        check("업로드 문서와 섹션 저장", result["doc"] == "uploaded_contract" and len(sections) == 2)
        check("S 등급 자동 확정", all(
            section["grade"] == "S" and section["classification_status"] == "auto_confirmed"
            for section in sections
        ))
        check("문서 등급은 섹션 Max", result["document_grade"] == "S")
        check("섹션별 자동 분류 이력", len(logs) == 2 and all(
            log["action"] == "auto_classified" for log in logs
        ))

        partial = FakeGemini(drop_ids={"fallback_contract#1"})
        partial_result = upload_pipeline.classify_and_store(
            "fallback_contract.md",
            CONTRACT_DOC,
            client=partial,
            db_path=db_path,
        )
        check("배치 누락 섹션만 개별 폴백", len(partial.models.calls) == 2)
        conn = get_conn(db_path)
        try:
            check("폴백 포함 모든 섹션 저장", len(
                store.sections_for_doc(partial_result["doc"], conn)
            ) == 2)
        finally:
            conn.close()

        low_confidence = FakeGemini(grade="C", confidence=0.55)
        pending_result = upload_pipeline.classify_and_store(
            "pending_contract.md",
            CONTRACT_DOC,
            client=low_confidence,
            db_path=db_path,
        )
        conn = get_conn(db_path)
        try:
            pending_sections = store.sections_for_doc(pending_result["doc"], conn)
        finally:
            conn.close()
        check("신뢰도 0.8 미만은 검수 대기", pending_result["pending_review"] == 2 and all(
            section["classification_status"] == "pending_review"
            for section in pending_sections
        ))

        conn = get_conn(db_path)
        try:
            skill = store.create_skill(
                "대형 계약",
                "대형 계약 금액과 비공개 할인 조건은 C로 분류하세요.",
                grade="C",
                keywords=["계약 금액", "할인 조건"],
                actor="reviewer",
                conn=conn,
            )
            conn.commit()
        finally:
            conn.close()

        skill_fake = FakeGemini(grade="C", applied_skills=[skill["name"]])
        skill_result = upload_pipeline.classify_and_store(
            "skill_contract.md",
            CONTRACT_DOC,
            client=skill_fake,
            db_path=db_path,
        )
        first_system_prompt = str(skill_fake.models.calls[0]["config"].system_instruction)
        conn = get_conn(db_path)
        try:
            skill_logs = [
                log
                for log in store.load_classification_logs(conn, doc=skill_result["doc"])
                if log["action"] == "skill_applied"
            ]
        finally:
            conn.close()
        check("활성 Skill을 다음 분류 프롬프트에 주입", "대형 계약" in first_system_prompt)
        check("실제 적용된 Skill만 이력 기록", len(skill_logs) == 2 and all(
            log["skill_id"] == skill["id"] for log in skill_logs
        ))

    print("\n업로드 파이프라인 테스트 통과 ✅")


if __name__ == "__main__":
    main()
