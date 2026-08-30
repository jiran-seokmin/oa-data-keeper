"""Deterministic CSO grade access-control engine.

Data and user grades share one ordered scale::

    O (Open) < S (Sensitive) < C (Classified)

Classification and access are deliberately separate concerns. A section is
readable only after its classification has been confirmed (automatically or by
a user), and only when the user's access grade is at least the section grade.
Missing or malformed security metadata always fails closed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


GRADES = ("O", "S", "C")
GRADE_NAMES = {
    "O": "Open",
    "S": "Sensitive",
    "C": "Classified · 기밀",
}
GRADE_RANKS = {grade: rank for rank, grade in enumerate(GRADES)}

CONFIRMED_CLASSIFICATION_STATUSES = frozenset({"auto_confirmed", "user_confirmed"})
CLASSIFICATION_STATUSES = CONFIRMED_CLASSIFICATION_STATUSES | {"pending_review"}


def normalize_grade(grade: object) -> str:
    """Return a canonical CSO grade or raise ``ValueError``.

    Runtime access decisions use :func:`_safe_grade` instead so bad metadata is
    denied rather than surfacing an exception. Write paths should call this
    strict helper before persisting data.
    """

    if not isinstance(grade, str):
        raise ValueError(f"grade must be one of {GRADES}: {grade!r}")
    normalized = grade.strip().upper()
    if normalized not in GRADE_RANKS:
        raise ValueError(f"grade must be one of {GRADES}: {grade!r}")
    return normalized


def _safe_grade(grade: object) -> str | None:
    try:
        return normalize_grade(grade)
    except ValueError:
        return None


def grade_rank(grade: object) -> int:
    """Return the rank of ``O``, ``S`` or ``C`` (0, 1 or 2)."""

    return GRADE_RANKS[normalize_grade(grade)]


def grade_from_legacy(value: object) -> str | None:
    """Map a legacy D/C numeric level to the CSO scale.

    Both legacy section grades (``D0`` ... ``D4``) and clearances
    (``C0`` ... ``C4``) use the same migration mapping:

    - 0 -> O
    - 1, 2, 3 -> S
    - 4 -> C

    Existing CSO strings pass through. ``None`` stays unclassified. Invalid
    values raise ``ValueError`` so migration cannot silently weaken access.
    """

    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip().upper()
        if stripped in GRADE_RANKS:
            return stripped
        if len(stripped) == 2 and stripped[0] in {"D", "C"} and stripped[1].isdigit():
            value = int(stripped[1])
        elif stripped.isdigit():
            value = int(stripped)
        else:
            raise ValueError(f"unsupported legacy grade: {value!r}")
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 4:
        raise ValueError(f"unsupported legacy grade: {value!r}")
    if value == 0:
        return "O"
    if value == 4:
        return "C"
    return "S"


def document_grade(sections: Iterable[Mapping[str, Any] | str | None]) -> str | None:
    """Derive a document's grade as the maximum grade of its sections.

    Documents never persist their own grade. Unclassified sections are ignored
    for the aggregate (their own access still defaults to denied). Invalid
    non-null grades raise instead of producing a potentially weaker result.
    """

    highest: str | None = None
    for section in sections:
        raw_grade = section.get("grade") if isinstance(section, Mapping) else section
        if raw_grade is None:
            continue
        grade = normalize_grade(raw_grade)
        if highest is None or grade_rank(grade) > grade_rank(highest):
            highest = grade
    return highest


@dataclass(frozen=True)
class Decision:
    """Binary access decision with audit-friendly, content-free reasons."""

    allowed: bool
    section_grade: str | None
    user_grade: str | None
    reasons: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "allowed" if self.allowed else "denied"


def decide(section: Mapping[str, Any], persona: Mapping[str, Any]) -> Decision:
    """Decide whether ``persona`` may read ``section``.

    ``pending_review`` and missing/unknown classification states are denied.
    Missing or malformed grades also deny access. No LLM or mutable policy is
    involved in this decision.
    """

    section_grade = _safe_grade(section.get("grade"))
    user_grade = _safe_grade(persona.get("access_grade"))
    classification_status = section.get("classification_status")

    if classification_status not in CONFIRMED_CLASSIFICATION_STATUSES:
        if classification_status == "pending_review":
            reason = "분류 검토 대기: 사용자 확인 전 접근 차단 (default-deny)"
        else:
            reason = "분류 미확정: 확인된 분류 상태가 없어 접근 차단 (default-deny)"
        return Decision(False, section_grade, user_grade, [reason])

    if section_grade is None:
        return Decision(False, None, user_grade, ["섹션 등급 누락 또는 오류: 접근 차단 (default-deny)"])

    if user_grade is None:
        return Decision(False, section_grade, None, ["사용자 접근 등급 누락 또는 오류: 접근 차단 (default-deny)"])

    allowed = grade_rank(user_grade) >= grade_rank(section_grade)
    if allowed:
        reason = f"접근 허용: 사용자 {user_grade} 등급이 섹션 {section_grade} 등급 이상"
    else:
        reason = f"접근 차단: 사용자 {user_grade} 등급이 섹션 {section_grade} 등급보다 낮음"
    return Decision(allowed, section_grade, user_grade, [reason])


def decide_all(
    sections: Iterable[Mapping[str, Any]], persona: Mapping[str, Any]
) -> list[tuple[Mapping[str, Any], Decision]]:
    return [(section, decide(section, persona)) for section in sections]
