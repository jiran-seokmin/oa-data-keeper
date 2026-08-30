"""CSO 권한 기반 LLM 컨텍스트 조립 테스트."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pipeline


def section(index: int, grade: str, text: str, status: str = "auto_confirmed") -> dict:
    return {
        "id": f"demo#{index}",
        "doc": "demo",
        "doc_title": "데모 문서",
        "title": f"전략 섹션 {index}",
        "text": text,
        "grade": grade,
        "confidence": 0.95,
        "classification_status": status,
        "classification_reason": "테스트",
        "keywords": ["전략"],
        "departments": [],
        "summary": "전략 요약",
        "confirmed_by": None,
        "confirmed_at": None,
    }


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="허용된 자료 기반 답변")],
        )


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main() -> None:
    sections = [
        section(0, "S", "내부 영업 전략을 검토합니다."),
        section(1, "C", "프로젝트 오로라 인수 전략입니다."),
        section(2, "S", "미확정 전략입니다.", "pending_review"),
    ]
    s_user = {"name": "내부 사용자", "access_grade": "S"}
    c_user = {"name": "기밀 사용자", "access_grade": "C"}

    client = FakeClient()
    result = pipeline.answer("전략", s_user, sections=sections, client=client)
    system = client.messages.calls[0]["system"]
    check("S 사용자 컨텍스트에는 S 섹션만 포함", "내부 영업 전략" in system)
    check("S 사용자 컨텍스트에서 C 원문 제외", "프로젝트 오로라" not in system)
    check("검수 대기 원문 제외", "미확정 전략" not in system)
    check("사용 섹션에는 허용된 ID만 반환", [item["id"] for item in result.used_sections] == ["demo#0"])

    c_client = FakeClient()
    c_result = pipeline.answer("전략", c_user, sections=sections, client=c_client)
    check("C 사용자는 확정 S/C 섹션 사용", {
        item["id"] for item in c_result.used_sections
    } == {"demo#0", "demo#1"})
    check("C 사용자도 검수 대기 섹션 제외", "미확정 전략" not in c_client.messages.calls[0]["system"])

    no_match_client = FakeClient()
    no_match = pipeline.answer("주차장", c_user, sections=sections, client=no_match_client)
    check("검색 결과 없음 안내", no_match.answer == pipeline.NO_MATCH_MESSAGE)
    check("검색 결과가 없으면 LLM 미호출", not no_match_client.messages.calls)

    follow_up_client = FakeClient()
    follow_up = pipeline.answer(
        "그 내용은?",
        s_user,
        sections=sections,
        client=follow_up_client,
        context_questions=["내부 영업 전략을 알려주세요."],
    )
    follow_up_prompt = follow_up_client.messages.calls[0]["messages"][0]["content"]
    check("후속 질문은 이전 질문으로 허용 섹션 검색", [
        item["id"] for item in follow_up.used_sections
    ] == ["demo#0"])
    check("LLM 입력에 이전 질문과 현재 질문 포함", all(
        value in follow_up_prompt for value in ("내부 영업 전략", "그 내용은?")
    ))
    check("응답 query는 현재 질문만 유지", follow_up.question == "그 내용은?")

    print("\nCSO 파이프라인 테스트 통과 ✅")


if __name__ == "__main__":
    main()
