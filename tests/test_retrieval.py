"""CSO 권한 우선 검색 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import retrieval


def section(index: int, grade: str | None, text: str, status: str = "auto_confirmed") -> dict:
    return {
        "id": f"demo#{index}",
        "doc": "demo",
        "doc_title": "데모 문서",
        "title": f"섹션 {index}",
        "text": text,
        "grade": grade,
        "confidence": 0.95,
        "classification_status": status,
        "classification_reason": "테스트",
        "keywords": text.split(),
        "departments": [],
        "summary": f"{grade or '미분류'} 요약",
        "confirmed_by": None,
        "confirmed_at": None,
    }


SECTIONS = [
    section(0, "O", "공개 제품 소개"),
    section(1, "S", "내부 영업 파이프라인"),
    section(2, "C", "비공개 인수 검토 오로라"),
    section(3, "S", "미확정 보상 계획", "pending_review"),
]
O_USER = {"name": "외부", "access_grade": "O"}
S_USER = {"name": "내부", "access_grade": "S"}
C_USER = {"name": "기밀", "access_grade": "C"}


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main() -> None:
    check("O 사용자는 공개 섹션 검색", len(
        retrieval.search_sections("제품 소개", O_USER, SECTIONS)
    ) == 1)
    check("O 사용자는 S 섹션 원문 키워드로도 검색 불가", not retrieval.search_sections(
        "영업 파이프라인", O_USER, SECTIONS
    ))
    check("S 사용자는 S 섹션 검색", len(
        retrieval.search_sections("영업 파이프라인", S_USER, SECTIONS)
    ) == 1)
    check("S 사용자는 C 섹션 존재·원문 모두 은닉", not retrieval.search_sections(
        "인수 오로라", S_USER, SECTIONS
    ))
    check("C 사용자는 C 섹션 검색", len(
        retrieval.search_sections("인수 오로라", C_USER, SECTIONS)
    ) == 1)
    check("검수 대기 섹션은 C 사용자도 검색 불가", not retrieval.search_sections(
        "미확정 보상", C_USER, SECTIONS
    ))
    follow_up = retrieval.search_sections_with_context(
        "그 내용은?", ["내부 영업 파이프라인을 알려주세요."], S_USER, SECTIONS
    )
    check("후속 질문은 같은 세션의 이전 질문으로 검색 보완", [
        item["id"] for item in follow_up
    ] == ["demo#1"])
    check("후속 질문 문맥도 사용자 등급을 넘지 못함", not retrieval.search_sections_with_context(
        "그 내용은?", ["내부 영업 파이프라인을 알려주세요."], O_USER, SECTIONS
    ))
    current_match = retrieval.search_sections_with_context(
        "제품 소개", ["내부 영업 파이프라인을 알려주세요."], S_USER, SECTIONS
    )
    check("현재 질문이 검색되면 이전 질문을 섞지 않음", [
        item["id"] for item in current_match
    ] == ["demo#0"])
    check("접근 수 집계", retrieval.access_counts(S_USER, SECTIONS) == (2, 2))

    print("\nCSO 검색 테스트 통과 ✅")


if __name__ == "__main__":
    main()
