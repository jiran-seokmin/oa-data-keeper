"""Streamlit review console for the DataKeeper C/S/O MVP.

Run with: ``streamlit run app/ui.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from app import governance, store


st.set_page_config(page_title="DataKeeper C/S/O", page_icon="🛡️", layout="wide")
st.title("DataKeeper")
st.caption("C/S/O 자동 분류 · 사용자 검수 · 확정 등급 기반 접근")


def _grade_label(grade: str | None) -> str:
    return {
        "O": "O · Open 공개",
        "S": "S · Sensitive 민감",
        "C": "C · Classified 기밀",
    }.get(grade, "미분류")


def _status_label(status: str) -> str:
    return {
        "auto_confirmed": "자동 확정",
        "pending_review": "검수 대기",
        "user_confirmed": "사용자 확정",
    }.get(status, status)


def classification_tab() -> None:
    sections = store.load_sections()
    pending = sum(section["classification_status"] == "pending_review" for section in sections)
    documents = store.load_documents()
    cols = st.columns(3)
    cols[0].metric("문서", len(documents))
    cols[1].metric("섹션", len(sections))
    cols[2].metric("검수 대기", pending)

    rows = [
        {
            "섹션 ID": section["id"],
            "문서": section["doc_title"],
            "섹션": section["title"],
            "등급": section["grade"] or "-",
            "신뢰도": section["confidence"],
            "상태": _status_label(section["classification_status"]),
            "분류 근거": section["classification_reason"],
        }
        for section in sections
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    if not sections:
        st.info("분류된 섹션이 없습니다.")
        return

    st.subheader("등급 검수 및 수정")
    selected_id = st.selectbox(
        "섹션",
        [section["id"] for section in sections],
        format_func=lambda section_id: next(
            f"{section['doc_title']} › {section['title']} ({_grade_label(section['grade'])})"
            for section in sections
            if section["id"] == section_id
        ),
    )
    section = next(item for item in sections if item["id"] == selected_id)
    st.text_area("원문", section["text"], height=180, disabled=True)
    if section["summary"]:
        st.caption(f"요약: {section['summary']}")

    with st.form("classification-review"):
        grade = st.selectbox(
            "확정 등급",
            ["O", "S", "C"],
            index=["O", "S", "C"].index(section["grade"] or "C"),
            format_func=_grade_label,
        )
        reason = st.text_input("판단 근거", value=section["classification_reason"])
        actor = st.text_input("검수자", value="reviewer")
        submitted = st.form_submit_button("등급 확정 및 Skill 반영", type="primary")
    if submitted:
        try:
            result = governance.confirm_and_learn(selected_id, grade, reason, actor)
        except (KeyError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.success(
                f"{_grade_label(result['section']['grade'])}로 확정하고 "
                f"분류 Skill을 {result['skill_action']} 처리했습니다."
            )
            st.rerun()


def access_tab() -> None:
    personas = store.load_personas()
    if not personas:
        st.info("등록된 사용자가 없습니다.")
        return
    persona_id = st.selectbox(
        "사용자",
        [persona["id"] for persona in personas],
        format_func=lambda value: next(
            f"{persona['name']} · {_grade_label(persona['access_grade'])}"
            for persona in personas
            if persona["id"] == value
        ),
    )
    persona = next(item for item in personas if item["id"] == persona_id)
    sections = store.load_accessible_sections(persona)
    st.caption("확정 상태이며 사용자 등급 이하인 원문만 조회됩니다. 미확정·상위 등급은 기본 차단됩니다.")
    if not sections:
        st.warning("이 사용자가 접근할 수 있는 확정 섹션이 없습니다.")
        return

    for section in sections:
        with st.expander(
            f"[{section['grade']}] {section['doc_title']} › {section['title']}",
            expanded=False,
        ):
            st.write(section["text"])


def logs_tab() -> None:
    classification_logs = store.load_classification_logs(limit=200)
    access_logs = store.load_access_logs(limit=200)
    skills = store.load_skills()

    st.subheader("분류·학습 이력")
    st.dataframe(pd.DataFrame(classification_logs), width="stretch", hide_index=True)
    st.subheader("접근 이력")
    st.caption("질문·답변·원문은 기록하지 않고 식별자, 등급, 허용/차단 건수만 저장합니다.")
    st.dataframe(pd.DataFrame(access_logs), width="stretch", hide_index=True)
    st.subheader("활성 분류 Skill")
    st.dataframe(pd.DataFrame(skills), width="stretch", hide_index=True)


tab_classification, tab_access, tab_logs = st.tabs(
    ["분류·학습", "권한 기반 조회", "판정·접근 로그"]
)
with tab_classification:
    classification_tab()
with tab_access:
    access_tab()
with tab_logs:
    logs_tab()
