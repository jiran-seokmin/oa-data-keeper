"""CSO 접근 판정 엔진 시나리오 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine import decide, document_grade, grade_from_legacy


O_USER = {"name": "외부 사용자", "access_grade": "O"}
S_USER = {"name": "내부 사용자", "access_grade": "S"}
C_USER = {"name": "기밀 사용자", "access_grade": "C"}


def section(grade: str | None, status: str = "auto_confirmed") -> dict:
    return {"grade": grade, "classification_status": status}


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main() -> None:
    check("기존 D0은 O로 변환", grade_from_legacy("D0") == "O")
    check("기존 D1~D3은 S로 변환", all(
        grade_from_legacy(f"D{level}") == "S" for level in (1, 2, 3)
    ))
    check("기존 D4는 C로 변환", grade_from_legacy("D4") == "C")

    check("O 사용자는 O 접근", decide(section("O"), O_USER).allowed)
    check("O 사용자는 S 차단", not decide(section("S"), O_USER).allowed)
    check("O 사용자는 C 차단", not decide(section("C"), O_USER).allowed)

    check("S 사용자는 O 접근", decide(section("O"), S_USER).allowed)
    check("S 사용자는 S 접근", decide(section("S"), S_USER).allowed)
    check("S 사용자는 C 차단", not decide(section("C"), S_USER).allowed)

    check("C 사용자는 O/S/C 모두 접근", all(
        decide(section(grade), C_USER).allowed for grade in ("O", "S", "C")
    ))

    check("검수 대기 섹션은 C 사용자도 차단", not decide(
        section("S", "pending_review"), C_USER
    ).allowed)
    check("미분류 섹션은 기본 차단", not decide(section(None, "pending_review"), C_USER).allowed)
    check("잘못된 사용자 등급도 기본 차단", not decide(
        section("O"), {"access_grade": "UNKNOWN"}
    ).allowed)

    check("문서 등급은 섹션 최고 등급", document_grade([
        section("O"), section("S"), section("C")
    ]) == "C")
    check("검수 대기 제안 등급도 문서 Max 표시에 반영", document_grade([
        section("O"), section("S", "pending_review")
    ]) == "S")

    print("\nCSO 판정 엔진 테스트 통과 ✅")


if __name__ == "__main__":
    main()
