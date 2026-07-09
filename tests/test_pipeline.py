"""Phase E LLM 답변 파이프라인 테스트. 실행: python tests/test_pipeline.py"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pipeline


POLICY = pipeline.load_policy()
SALES_REP = {"name": "영업팀원", "clearance": 2, "department": "영업팀", "channel": "internal"}


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = "실드락 인수 건은 검토 중입니다." if len(self.calls) == 1 else "[기업명A] 인수 건은 검토 중입니다."
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
        )


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


class FakeModels:
    """실제 google-genai API 형태: client.models.generate_content(...) → resp.text"""

    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        text = "실드락 인수 건은 검토 중입니다." if len(self.calls) == 1 else "[기업명A] 인수 건은 검토 중입니다."
        return SimpleNamespace(text=text)


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeModels()


def check(name, cond):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}")
    assert cond, name


def main():
    sections = [
        {
            "id": "demo#0",
            "doc": "demo",
            "doc_title": "데모 문서",
            "title": "비공개 인수 검토",
            "text": "실드락 인수 검토가 진행 중입니다.",
            "security_level": 4,
            "confidence": 0.95,
            "needs_review": True,
            "keywords": ["인수", "검토"],
            "departments": ["경영진"],
            "summary_generalized": "비공개 전략 검토 사안이 존재함.",
            "entities": [{"text": "실드락", "placeholder": "[기업명A]", "type": "기업명"}],
        },
        {
            "id": "demo#1",
            "doc": "demo",
            "doc_title": "데모 문서",
            "title": "공개 개요",
            "text": "제품 공개 개요입니다.",
            "security_level": 0,
            "confidence": 0.95,
            "needs_review": False,
            "keywords": ["공개"],
            "departments": [],
            "summary_generalized": "제품 공개 개요.",
            "entities": [],
        },
    ]
    client = FakeClient()
    result = pipeline.answer("인수 검토", SALES_REP, sections=sections, policy=POLICY, client=client)

    check("검색 결과 기반 used_sections 반환", [s["id"] for s in result.used_sections] == ["demo#0"])
    check("C2 × D4는 A3 마스킹으로 프롬프트 진입", result.used_sections[0]["mode"] == 3)
    check("프롬프트에 원문 엔티티 미포함", "실드락" not in client.messages.calls[0]["system"])
    check("프롬프트에 플레이스홀더 포함", "[기업명A]" in client.messages.calls[0]["system"])
    check("출력 가드 유출 감지", result.guard.triggered is True)
    check("출력 가드 1회 재시도", result.guard.retried is True and len(client.messages.calls) == 2)
    check("최종 답변은 마스킹 플레이스홀더 유지", result.answer == "[기업명A] 인수 건은 검토 중입니다.")

    # ── A1(노출 제한): C3는 원문을 '배경 전용'으로 프롬프트에 받아 추론하되, 출력가드가 유출 방어 ──
    SALES_LEAD = {"name": "영업팀장", "clearance": 3, "department": "영업팀", "channel": "internal"}
    lead_client = FakeClient()
    result_lead = pipeline.answer("인수 검토", SALES_LEAD, sections=sections, policy=POLICY, client=lead_client)
    lead_system = lead_client.messages.calls[0]["system"]
    check("C3 × D4는 A1 노출제한으로 판정", result_lead.used_sections[0]["mode"] == 1)
    check("A1: 원문이 '배경 전용' 태그로 프롬프트 진입 (LLM 추론 근거)",
          "[A1 배경 전용" in lead_system and "실드락" in lead_system)
    check("A1: LLM 유출 시 출력가드 재시도", result_lead.guard.retried is True)
    check("A1: 최종 답변에 원문 엔티티 미포함", "실드락" not in result_lead.answer)

    gemini = FakeGeminiClient()
    result_gemini = pipeline.answer("인수 검토", SALES_REP, sections=sections, policy=POLICY, client=gemini)
    first_call = gemini.models.calls[0]
    check("Gemini는 models.generate_content 호출", "config" in first_call and "contents" in first_call)
    check("Gemini system_instruction에 원문 엔티티 미포함", "실드락" not in first_call["config"].system_instruction)
    check("Gemini 출력 가드 재시도", result_gemini.guard.retried is True and len(gemini.models.calls) == 2)

    print("\n전체 테스트 통과 ✅")


if __name__ == "__main__":
    main()
