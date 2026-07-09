"use strict";

// 접근 모드 시각 설정 (기존 Streamlit UI 팔레트 재사용)
const MODE = {
  0: { name: "A0 전체 접근", badge: "✅", bg: "#d3f1e0", fg: "#0b6e4f" },
  1: { name: "A1 노출 제한", badge: "🧠", bg: "#e6dcf7", fg: "#5b3fa8" },
  2: { name: "A2 의미 제한", badge: "🔍", bg: "#fff3bf", fg: "#8a6d00" },
  3: { name: "A3 정보 마스킹", badge: "🎭", bg: "#fde2cd", fg: "#a4540a" },
  4: { name: "A4 접근 차단", badge: "🚫", bg: "#f1f3f4", fg: "#5f6368" },
};
const LEVEL_COLOR = { 0: "#2a9d8f", 1: "#6c9a3f", 2: "#e9a03b", 3: "#d1495b", 4: "#7b2d43" };

const $ = (id) => document.getElementById(id);
const personaSel = $("persona");
const purposeChk = $("purpose");
const messages = $("messages");
const composer = $("composer");
const qInput = $("q");

let personas = [];

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// A3 마스킹본의 [플레이스홀더]를 하이라이트
function highlightPlaceholders(escaped) {
  return escaped.replace(/\[[^\]]+\]/g, (m) => `<mark>${m}</mark>`);
}

async function loadPersonas() {
  personas = await (await fetch("/api/personas")).json();
  personaSel.innerHTML = personas
    .map((p) => `<option value="${p.id}">${esc(p.name)} — C${p.clearance}${p.department ? " · " + esc(p.department) : " · 외부 채널"}</option>`)
    .join("");
  personaSel.value = "sales_rep"; // 데모 기본값
}

function currentPersona() {
  return personas.find((p) => p.id === personaSel.value);
}

function scrollDown() {
  messages.scrollTop = messages.scrollHeight;
}

function addUserMessage(text, persona, purpose) {
  const hint = $("hint");
  if (hint) hint.remove();
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `<span class="bubble-user">${esc(text)}</span>
    <div class="ctx-line">👤 <b>${esc(persona.name)}</b> · C${persona.clearance} · ${persona.department ? esc(persona.department) : "외부 채널"} · 목적: ${purpose === "judgment" ? "판단/집계" : "정보 조회"}</div>`;
  messages.appendChild(div);
  scrollDown();
}

function cardHTML(r) {
  const m = MODE[r.mode];
  const dColor = LEVEL_COLOR[r.security_level];
  let body;
  if (r.mode === 1 || r.content_hidden) {
    body = `<div class="body hidden">🔒 ${esc(r.rendered)}</div>`;
  } else if (r.mode === 2) {
    body = `<div class="body summary"><b>일반화 요약</b> · 원문 대신 요약으로 제공<br/>${esc(r.rendered)}</div>`;
  } else if (r.mode === 3) {
    body = `<div class="body">${highlightPlaceholders(esc(r.rendered))}</div>`;
  } else {
    body = `<div class="body">${esc(r.rendered)}</div>`;
  }
  const reasons = (r.reasons || []).map((x) => `<li>${esc(x)}</li>`).join("");
  const matched = (r.matched || []).length
    ? `<span class="matched">🔎 ${r.matched.map(esc).join(", ")}</span>` : "";
  return `<div class="card" style="border-left-color:${dColor}">
    <div class="card-head">
      <span class="badge d" style="background:${dColor}">D${r.security_level}</span>
      <span class="badge" style="background:${m.bg};color:${m.fg}">${m.badge} ${m.name}</span>
      <span class="sec-title">${esc(r.title)}</span>
      <span class="doc-title">· ${esc(r.doc_title)}</span>
      ${matched}
    </div>
    ${body}
    <details class="reasons">
      <summary>판정 근거 (gap=${r.gap})</summary>
      <ul class="reason-list">${reasons}</ul>
    </details>
  </div>`;
}

function addResponse(data) {
  const div = document.createElement("div");
  div.className = "msg bot";
  if (!data.results.length) {
    div.innerHTML = `<div class="empty">🔒 접근 권한 내에서 관련 정보를 찾지 못했습니다. 다른 사용자로 전환하거나 질문을 바꿔 보세요.</div>`;
  } else {
    const head = `<div class="summary-head">🤖 접근 등급에 맞게 <b>${data.results.length}개</b> 섹션을 조회했습니다. (원문·요약·마스킹·노출제한이 섞여 있을 수 있습니다)</div>`;
    div.innerHTML = head + data.results.map(cardHTML).join("");
  }
  messages.appendChild(div);
  scrollDown();
}

composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = qInput.value.trim();
  if (!q) return;
  const persona = currentPersona();
  const purpose = purposeChk.checked ? "judgment" : "info";
  addUserMessage(q, persona, purpose);
  qInput.value = "";
  const btn = composer.querySelector("button");
  btn.disabled = true;
  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_id: persona.id, question: q, purpose }),
    });
    addResponse(await res.json());
  } catch (err) {
    addResponse({ results: [] });
  } finally {
    btn.disabled = false;
    qInput.focus();
  }
});

loadPersonas();
