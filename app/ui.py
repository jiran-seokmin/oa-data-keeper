"""DataKeeper 데모 UI — 페르소나별 문서 렌더링 시각화.

MVP 초점: 입력 데이터를 보안 등급으로 분류하고, 페르소나에 따라 접근이
제어되는 것을 시각적으로 보여준다 (CONCEPT.md 6장). 실시간 질의응답은
Phase 2이며 마지막 탭에 보너스로만 존재한다.

실행: streamlit run app/ui.py  (뷰어·매트릭스는 API 키 불필요)
"""

from __future__ import annotations

import html
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from app.engine import MODE_NAMES, Decision, decide
from app.pipeline import load_personas, load_policy, load_sections

st.set_page_config(page_title="DataKeeper — 접근 제어 엔진 데모", page_icon="🔐", layout="wide")

MODE_BADGES = {0: "🚫", 1: "🎭", 2: "🔍", 3: "🧠", 4: "✅"}
MODE_COLORS = {0: "#f1f3f4", 1: "#fde2cd", 2: "#fff3bf", 3: "#e6dcf7", 4: "#d3f1e0"}
MODE_TEXT = {0: "#5f6368", 1: "#a4540a", 2: "#8a6d00", 3: "#5b3fa8", 4: "#0b6e4f"}
LEVEL_COLORS = {0: "#2a9d8f", 1: "#6c9a3f", 2: "#e9a03b", 3: "#d1495b", 4: "#7b2d43"}


@st.cache_data
def _sections():
    return load_sections()


@st.cache_data
def _policy():
    return load_policy()


@st.cache_data
def _personas():
    return load_personas()


def esc(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def level_badge(level: int) -> str:
    return (
        f'<span style="background:{LEVEL_COLORS[level]};color:#fff;border-radius:10px;'
        f'padding:1px 10px;font-size:0.78rem;font-weight:700">D{level}</span>'
    )


def mode_badge(d: Decision) -> str:
    return (
        f'<span style="background:{MODE_COLORS[d.mode]};color:{MODE_TEXT[d.mode]};border-radius:10px;'
        f'padding:1px 10px;font-size:0.78rem;font-weight:700">{MODE_BADGES[d.mode]} {MODE_NAMES[d.mode]}</span>'
    )


def masked_html(section: dict) -> str:
    """A1: 엔티티를 하이라이트된 플레이스홀더로 치환한 본문 HTML."""
    text = section["text"]
    for e in sorted(section.get("entities", []), key=lambda e: len(e["text"]), reverse=True):
        text = text.replace(e["text"], f"\x00{e['placeholder']}\x01")
    text = esc(text)
    text = text.replace("\x00", '<mark style="background:#ffd166;border-radius:4px;padding:0 5px;font-weight:600">')
    text = text.replace("\x01", "</mark>")
    return text


def render_section(section: dict, d: Decision) -> None:
    """CONCEPT.md 6.1절 렌더링 규칙의 구현."""
    with st.container(border=True):
        st.markdown(
            f'{level_badge(d.security_level)} &nbsp; **{section["title"]}** &nbsp; {mode_badge(d)}',
            unsafe_allow_html=True,
        )
        st.caption(f"gap={d.gap} · " + " / ".join(d.reasons))

        if d.mode == 0:
            st.markdown(
                '<div style="color:#9aa0a6;padding:6px 0">🔒 접근 차단 — 이 섹션은 현재 사용자에게 제공되지 않습니다.</div>',
                unsafe_allow_html=True,
            )
        elif d.mode == 1:
            st.markdown(
                f'<div style="line-height:1.7">{masked_html(section)}</div>',
                unsafe_allow_html=True,
            )
        elif d.mode == 2:
            st.markdown(
                '<div style="background:#fffbe8;border-left:4px solid #e9c46a;border-radius:6px;padding:10px 14px;line-height:1.7">'
                f'<b>일반화 요약</b> · 원문은 접근 등급이 부족해 요약으로 대체되었습니다<br>{esc(section["summary_generalized"])}</div>',
                unsafe_allow_html=True,
            )
        elif d.mode == 3:
            st.markdown(
                '<div style="color:#5b3fa8;font-size:0.85rem;margin-bottom:4px">'
                "🧠 AI 추론 근거로만 사용 가능 — 직접 열람 불가 (Phase 2 질의응답에서 판단·집계에만 활용)</div>"
                f'<div style="filter:blur(5px);user-select:none;pointer-events:none;line-height:1.7">{esc(section["text"])}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f'<div style="line-height:1.7">{esc(section["text"])}</div>', unsafe_allow_html=True)


def doc_list(sections: list[dict]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for s in sections:
        seen.setdefault(s["doc"], s["doc_title"])
    return list(seen.items())


def _mode_counts(decisions: list[Decision]) -> list[tuple[int, int]]:
    counts: dict[int, int] = {}
    for d in decisions:
        counts[d.mode] = counts.get(d.mode, 0) + 1
    return sorted(counts.items())


def log_view(persona: dict, doc_title: str, decisions: list[Decision]) -> None:
    st.session_state.setdefault("audit", [])
    entry = {
        "시각": datetime.now().strftime("%H:%M:%S"),
        "사용자": f"{persona['name']} (C{persona['clearance']})",
        "문서": doc_title,
        "판정": " · ".join(f"A{m}×{n}" for m, n in _mode_counts(decisions)),
    }
    audit = st.session_state["audit"]
    if not audit or (audit[-1]["사용자"], audit[-1]["문서"]) != (entry["사용자"], entry["문서"]):
        audit.append(entry)


# ── 탭 구현 ──────────────────────────────────────────────────────────────


def tab_viewer(sections, policy, persona, purpose):
    docs = doc_list(sections)
    by_doc = {doc: [s for s in sections if s["doc"] == doc] for doc, _ in docs}

    def label(item):
        doc, title = item
        modes = [decide(s, persona, policy, purpose).mode for s in by_doc[doc]]
        if all(m == 0 for m in modes):
            return f"🔒 {title}"
        if any(m < 4 for m in modes):
            return f"🔐 {title}"
        return f"📄 {title}"

    selected = st.selectbox("문서 선택", docs, format_func=label, index=4)
    doc, doc_title = selected

    decisions = [decide(s, persona, policy, purpose) for s in by_doc[doc]]
    log_view(persona, doc_title, decisions)

    st.markdown(f"### {doc_title}")
    st.caption(
        f"현재 사용자: **{persona['name']}** (C{persona['clearance']}"
        + (f", {persona['department']}" if persona.get("department") else ", 외부 채널")
        + ") — 사이드바에서 페르소나를 바꾸면 아래 렌더링이 실시간으로 바뀝니다."
    )
    for s, d in zip(by_doc[doc], decisions):
        render_section(s, d)


def tab_matrix(sections, personas, policy, purpose):
    st.caption("섹션 × 페르소나 전체 판정을 한 화면에. 색이 곧 접근 모드입니다.")
    legend = " &nbsp; ".join(
        f'<span style="background:{MODE_COLORS[m]};color:{MODE_TEXT[m]};border-radius:8px;'
        f'padding:2px 10px;font-size:0.8rem;font-weight:600">A{m} {MODE_NAMES[m].split(maxsplit=1)[1]}</span>'
        for m in range(5)
    )
    st.markdown(legend, unsafe_allow_html=True)

    rows = []
    for s in sections:
        row = {"문서": s["doc_title"], "섹션": s["title"], "D": f"D{s['security_level']}"}
        for p in personas:
            row[p["name"]] = f"A{decide(s, p, policy, purpose).mode}"
        rows.append(row)
    df = pd.DataFrame(rows)

    persona_cols = [p["name"] for p in personas]

    def color(v):
        if isinstance(v, str) and v.startswith("A") and v[1:].isdigit():
            m = int(v[1:])
            return f"background-color:{MODE_COLORS[m]};color:{MODE_TEXT[m]};font-weight:600"
        return ""

    styler = df.style
    styler = styler.map(color, subset=persona_cols) if hasattr(styler, "map") else styler.applymap(color, subset=persona_cols)
    st.dataframe(styler, use_container_width=True, hide_index=True, height=min(38 * len(df) + 40, 900))


def tab_ingest(sections):
    st.caption("수집 파이프라인 산출물 — 문서가 섹션으로 분리되고, 섹션마다 D등급·키워드·엔티티·A2용 요약이 부여된다.")
    rows = []
    for s in sections:
        rows.append({
            "섹션 ID": s["id"],
            "문서": s["doc_title"],
            "섹션": s["title"],
            "D등급": f"D{s['security_level']}",
            "신뢰도": s.get("confidence", 0),
            "검수": "⚠️" if s.get("needs_review") else "",
            "키워드": ", ".join(s.get("keywords", [])),
            "담당 부서": ", ".join(s.get("departments", [])),
            "엔티티": len(s.get("entities", [])),
            "A2 일반화 요약": s.get("summary_generalized", ""),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    sid = st.selectbox("엔티티 상세 보기", [s["id"] for s in sections if s.get("entities")])
    sec = next(s for s in sections if s["id"] == sid)
    st.dataframe(pd.DataFrame(sec["entities"]), hide_index=True)


def tab_audit():
    if st.session_state.get("audit"):
        st.dataframe(pd.DataFrame(st.session_state["audit"]), use_container_width=True, hide_index=True)
    else:
        st.info("아직 열람 기록이 없습니다. 문서 뷰어에서 문서를 열어보세요.")


def tab_chat(sections, policy, persona, purpose):
    st.caption(
        "Phase 2 미리보기 — 판정 엔진의 출력을 LLM 컨텍스트 조립에 적용한 실시간 질의응답. "
        "`ANTHROPIC_API_KEY` 필요 (MVP 데모의 필수 경로 아님)."
    )
    question = st.text_input("질문", placeholder="예: 현재 논의 중인 고객사들은 어디가 있나요?")
    if st.button("질문하기", type="primary", disabled=not question):
        from app.pipeline import answer
        try:
            with st.spinner(f"{persona['name']}(C{persona['clearance']}) 관점에서 생성 중…"):
                result = answer(question, persona, purpose, sections, policy)
            st.markdown(result.answer)
            if result.guard.triggered:
                if result.guard.blocked:
                    st.error(f"🛡️ 출력 가드가 답변을 차단했습니다. 감지된 유출: {', '.join(result.guard.leaked)}")
                else:
                    st.warning(f"🛡️ 출력 가드가 유출을 감지해 재생성했습니다. (1차 유출: {', '.join(result.guard.leaked)})")
        except Exception as e:
            st.error(f"답변 생성 실패: {e}\n\n`ANTHROPIC_API_KEY` 환경 변수를 확인하세요.")


def main():
    st.title("🔐 DataKeeper — 접근 제어 엔진 데모")
    st.caption(
        "All Data, Safe for Everyone — 데이터 보안 등급(D) × 사용자 접근 등급(C) × 상황 → "
        "섹션 단위 5단계 접근 모드(A) 판정. 같은 문서가 보는 사람에 따라 다르게 렌더링됩니다."
    )

    sections = _sections()
    policy = _policy()
    personas = _personas()

    with st.sidebar:
        st.header("사용자 (페르소나)")
        persona = st.radio(
            "누구로 볼까요?",
            personas,
            format_func=lambda p: f"{p['name']} — C{p['clearance']}"
            + (f" · {p['department']}" if p.get("department") else " · 외부 채널"),
        )
        st.divider()
        judgment = st.toggle(
            "판단/집계 목적 (A3 승격)",
            value=False,
            help="판단·집계 목적의 접근이면 A1/A2 판정 섹션이 A3(AI 추론 근거 전용)로 승격됩니다. D4는 승격되지 않습니다.",
        )
        st.divider()
        st.caption(f"코퍼스: 문서 12개 / 섹션 {len(sections)}개\n\n분류는 수집 시 1회 — 뷰어·매트릭스는 API 호출 없이 동작합니다.")

    purpose = "judgment" if judgment else "info"

    viewer, matrix, ingest, audit, chat = st.tabs(
        ["📄 문서 뷰어", "🗺️ 판정 매트릭스", "⚙️ 수집 결과", "📋 감사 로그", "💬 질의응답 (Phase 2)"]
    )
    with viewer:
        tab_viewer(sections, policy, persona, purpose)
    with matrix:
        tab_matrix(sections, personas, policy, purpose)
    with ingest:
        tab_ingest(sections)
    with audit:
        tab_audit()
    with chat:
        tab_chat(sections, policy, persona, purpose)


main()
