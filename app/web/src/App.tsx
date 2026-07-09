import { CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileText, Info, Lock, Send, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";

/* ── 타입 ─────────────────────────────────────────────── */
type Persona = {
  id: string;
  name: string;
  clearance: number;
  department: string | null;
  channel: "internal" | "external";
};
type Segment = { text: string; kind: "plain" | "hl" | "mask" };
type SectionView = {
  id: string;
  doc: string;
  doc_title: string;
  title: string;
  d: number;
  d_name: string;
  mode: number;
  mode_name: string;
  gap: number;
  reason: string;
  reasons: string[];
  keywords: string[];
  summary: string;
  departments: string[];
  kind: "full" | "exposure" | "semantic" | "mask" | "blocked";
  segments?: Segment[];
  blur_text?: string;
};
type DocView = { doc: string; doc_title: string; dept_label: string; sections: SectionView[] };
type MatrixCell = { persona_id: string; mode: number; mode_name: string; reason: string };
type MatrixRow = { id: string; doc: string; doc_title: string; title: string; d: number; cells: MatrixCell[] };
type RetrievalResult = {
  id: string;
  doc: string;
  doc_title: string;
  title: string;
  security_level: number;
  mode: number;
  mode_name: string;
};
type Guard = { triggered: boolean; leaked: string[]; retried: boolean; blocked: boolean };
type ChatSource = { title: string; d: number; mode: number; mode_name: string };
type ChatMsg = {
  id: string;
  q: string;
  answer: string;
  sources: ChatSource[];
  guard?: Guard;
  fallback?: boolean;
};

/* ── canonical A모드 · D등급 (디자인 팔레트, PRD 표기) ── */
const MODES: Record<number, { name: string; desc: string; fg: string; bg: string }> = {
  0: { name: "전체 접근", desc: "원문 그대로 제공", fg: "#166534", bg: "#DCFCE7" },
  1: { name: "노출 제한", desc: "AI 추론 근거 전용", fg: "#5B21B6", bg: "#EDE9FE" },
  2: { name: "의미 제한", desc: "일반화 요약으로 대체", fg: "#1E40AF", bg: "#DBEAFE" },
  3: { name: "정보 마스킹", desc: "엔티티를 플레이스홀더로 치환", fg: "#9A3412", bg: "#FFEDD5" },
  4: { name: "접근 차단", desc: "검색·목록에서 제외", fg: "#4B5563", bg: "#F3F4F6" },
};
const DMETA: Record<number, { fg: string; bg: string }> = {
  0: { fg: "#4B5563", bg: "#F3F4F6" },
  1: { fg: "#166534", bg: "#DCFCE7" },
  2: { fg: "#854D0E", bg: "#FEF9C3" },
  3: { fg: "#9A3412", bg: "#FFEDD5" },
  4: { fg: "#991B1B", bg: "#FEE2E2" },
};
const EXAMPLES = [
  "현재 논의 중인 고객사는 어디인가요?",
  "예상 계약 규모는 얼마인가요?",
  "인수 검토 중인 건이 있나요?",
  "DataKeeper는 어떤 제품인가요?",
];

/* ── 유틸 ─────────────────────────────────────────────── */
const personaImg = (c: number) => `/personas/c${c}.svg`;
const nextId = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;

function chip(m: { fg: string; bg: string }): CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", gap: 4, padding: "1px 8px",
    borderRadius: 5, fontSize: 11, fontWeight: 600, background: m.bg, color: m.fg,
    whiteSpace: "nowrap", lineHeight: "18px",
  };
}
function cChip(sel: boolean): CSSProperties {
  return {
    display: "inline-flex", padding: "1px 7px", borderRadius: 5, fontSize: 10.5, fontWeight: 700,
    background: sel ? "rgba(255,255,255,.18)" : "#F3F4F6", color: sel ? "#FFFFFF" : "#111827",
    border: sel ? "1px solid rgba(255,255,255,.25)" : "1px solid #E5E7EB",
    lineHeight: "15px", whiteSpace: "nowrap",
  };
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}
async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

/* ── 공통 소형 컴포넌트 ───────────────────────────────── */
function Segments({ segs }: { segs: Segment[] }) {
  return (
    <>
      {segs.map((g, i) => {
        if (g.kind === "hl")
          return <span key={i} style={{ borderBottom: "2px solid #D1D5DB", fontWeight: 500, color: "#111827" }}>{g.text}</span>;
        if (g.kind === "mask")
          return <span key={i} style={{ background: "#FFEDD5", color: "#9A3412", borderRadius: 4, padding: "0 4px", fontWeight: 600 }}>{g.text}</span>;
        return <span key={i}>{g.text}</span>;
      })}
    </>
  );
}
const DBadge = ({ d, name }: { d: number; name?: string }) => (
  <span style={chip(DMETA[d])}>D{d}{name ? ` ${name}` : ""}</span>
);
const ABadge = ({ mode }: { mode: number }) => (
  <span style={chip(MODES[mode])}>A{mode} {MODES[mode].name}</span>
);
const AiBadge = ({ text }: { text: string }) => (
  <span style={{ display: "inline-flex", gap: 6, alignItems: "center", background: "#111827", color: "#FFFFFF", borderRadius: 6, padding: "4px 12px", fontSize: 11, fontWeight: 600 }}>
    <Sparkles size={12} /> {text}
  </span>
);

function MarkdownAnswer({ children }: { children: string }) {
  return (
    <div className="dk-markdown">
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}

function DocumentSidebar({ docs, activeDoc, onSelectDoc }: { docs: DocView[]; activeDoc: DocView | null; onSelectDoc: (doc: string) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#9CA3AF", padding: "0 2px" }}>문서함</div>
      {docs.map((d) => {
        const locked = d.sections.every((s) => s.kind === "blocked");
        const active = activeDoc?.doc === d.doc;
        return (
          <div key={d.doc} onClick={() => onSelectDoc(d.doc)}
            style={{ padding: "12px 14px", borderRadius: 8, cursor: "pointer", background: "#FFFFFF", border: active ? "1px solid #111827" : "1px solid #E5E7EB", boxShadow: active ? "0 0 0 1px #111827" : "0 1px 2px rgba(0,0,0,.04)", opacity: locked ? 0.68 : 1 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>{d.doc_title}</div>
                <div style={{ fontSize: 11.5, color: "#9CA3AF", marginTop: 2 }}>{d.sections.length}개 섹션 · {d.dept_label}</div>
              </div>
              {locked && <Lock size={14} color="#9CA3AF" />}
            </div>
          </div>
        );
      })}
      <div style={{ marginTop: 8, padding: 14, borderRadius: 8, background: "#FFFFFF", border: "1px solid #E5E7EB" }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#9CA3AF", marginBottom: 8 }}>접근 모드</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {[0, 1, 2, 3, 4].map((m) => (
            <div key={m} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={chip(MODES[m])}>A{m}</span>
              <span style={{ fontSize: 11.5, color: "#4B5563" }}>{MODES[m].desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── 앱 ───────────────────────────────────────────────── */
type View = "grid" | "viewer" | "chat" | "matrix";

export function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [personaId, setPersonaId] = useState("sales_rep");
  const [view, setView] = useState<View>("grid");
  const [docs, setDocs] = useState<DocView[]>([]);
  const [matrix, setMatrix] = useState<{ personas: Persona[]; rows: MatrixRow[] } | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const [focusSec, setFocusSec] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  useEffect(() => {
    getJson<Persona[]>("/api/personas").then((data) => {
      setPersonas(data);
      if (!data.some((p) => p.id === personaId)) setPersonaId(data[0]?.id ?? "");
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!personaId) return;
    getJson<{ docs: DocView[] }>(`/api/sections?persona_id=${personaId}`).then((data) => {
      setDocs(data.docs);
      setDocId((cur) => cur ?? data.docs[0]?.doc ?? null);
    });
  }, [personaId]);

  useEffect(() => {
    if (view === "matrix" && !matrix)
      getJson<{ personas: Persona[]; rows: MatrixRow[] }>("/api/matrix").then(setMatrix);
  }, [view, matrix]);

  const persona = useMemo(
    () => personas.find((p) => p.id === personaId) ?? personas[0] ?? null,
    [personaId, personas],
  );

  const send = useCallback(
    async (text: string) => {
      const q = text.trim();
      if (!q || !persona || chatLoading) return;
      setChatInput("");
      setChatLoading(true);
      const payload = { persona_id: persona.id, question: q, purpose: "info" };
      try {
        let msg: ChatMsg;
        try {
          const data = await postJson<{ answer: string; used_sections: RetrievalResult[]; guard: Guard }>("/api/chat", payload);
          msg = {
            id: nextId(), q, answer: data.answer,
            sources: data.used_sections.map((s) => ({ title: `${s.doc_title} › ${s.title}`, d: s.security_level, mode: s.mode, mode_name: s.mode_name })),
            guard: data.guard,
          };
        } catch {
          const data = await postJson<{ results: RetrievalResult[] }>("/api/search", payload);
          msg = {
            id: nextId(), q,
            answer: data.results.length
              ? "LLM 답변 모드를 사용할 수 없어 조회 모드로 전환했습니다. 접근 등급에 맞는 관련 섹션을 근거로 표시합니다."
              : "접근 권한 내에서 관련 정보를 찾지 못했습니다.",
            sources: data.results.map((s) => ({ title: `${s.doc_title} › ${s.title}`, d: s.security_level, mode: s.mode, mode_name: s.mode_name })),
            fallback: true,
          };
        }
        setChat((prev) => [...prev, msg]);
      } catch (e) {
        setChat((prev) => [...prev, { id: nextId(), q, answer: `요청 처리에 실패했습니다. ${e instanceof Error ? e.message : ""}`, sources: [] }]);
      } finally {
        setChatLoading(false);
      }
    },
    [persona, chatLoading],
  );

  const activeDoc = docs.find((d) => d.doc === docId) ?? docs[0] ?? null;
  const openInViewer = (doc: string, secId: string) => {
    setDocId(doc);
    setFocusSec(secId);
    setView("viewer");
  };

  const navItems: { id: View; label: string }[] = [
    { id: "grid", label: "판정 그리드" },
    { id: "viewer", label: "문서 뷰어" },
    { id: "chat", label: "채팅" },
    { id: "matrix", label: "매트릭스" },
  ];

  return (
    <div className="dk-app">
      <header className="dk-header">
        <div className="dk-brand-mark"><Lock size={16} /></div>
        <div>
          <div className="dk-brand-title">DataKeeper</div>
          <div className="dk-brand-sub">접근 제어 엔진 — All Data, Safe for Everyone</div>
        </div>
        <div className="dk-nav">
          {navItems.map((n) => (
            <div key={n.id} className={`dk-tab${view === n.id ? " active" : ""}`} onClick={() => setView(n.id)}>{n.label}</div>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {persona && (
          <div className="dk-cur-persona">
            <img src={personaImg(persona.clearance)} alt="" />
            <span className="dk-cur-name">{persona.name}</span>
            <span style={cChip(false)}>C{persona.clearance}</span>
          </div>
        )}
      </header>

      <div className="dk-persona-bar">
        <span className="dk-persona-label">페르소나</span>
        {personas.map((p) => {
          const sel = p.id === personaId;
          return (
            <div key={p.id} className={`dk-persona-chip${sel ? " sel" : ""}`} onClick={() => setPersonaId(p.id)}>
              <img src={personaImg(p.clearance)} alt="" />
              <span className="nm">{p.name}</span>
              <span className="role" style={{ color: sel ? "rgba(255,255,255,.7)" : "#9CA3AF" }}>{p.department ?? "미인증 채널"}</span>
              <span style={cChip(sel)}>C{p.clearance}</span>
            </div>
          );
        })}
      </div>

      <main className="dk-main">
        {view === "grid" && <GridView docs={docs} activeDoc={activeDoc} persona={persona} onSelectDoc={(d) => { setDocId(d); setFocusSec(null); }} onOpen={openInViewer} />}
        {view === "viewer" && <ViewerView docs={docs} activeDoc={activeDoc} persona={persona} focusSec={focusSec} onSelectDoc={(d) => { setDocId(d); setFocusSec(null); }} />}
        {view === "chat" && (
          <ChatView persona={persona} chat={chat} loading={chatLoading} input={chatInput}
            onInput={setChatInput} onSend={() => send(chatInput)} onSuggest={send} />
        )}
        {view === "matrix" && <MatrixView data={matrix} docs={docs} activeDoc={activeDoc} personaId={personaId} onPick={setPersonaId} onSelectDoc={(d) => { setDocId(d); setFocusSec(null); }} />}
      </main>
    </div>
  );
}

/* ── 판정 그리드 ─────────────────────────────────────── */
function ModeLegend() {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {[0, 1, 2, 3, 4].map((m) => (
        <span key={m} style={chip(MODES[m])}>A{m} {MODES[m].name}</span>
      ))}
    </div>
  );
}

function GridView({ docs, activeDoc, persona, onSelectDoc, onOpen }: {
  docs: DocView[]; activeDoc: DocView | null; persona: Persona | null; onSelectDoc: (doc: string) => void; onOpen: (doc: string, sec: string) => void;
}) {
  const cols = "minmax(240px, 1.6fr) minmax(190px, 1fr) 150px 120px";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "264px minmax(0, 1fr)", gap: 20, alignItems: "start" }}>
      <DocumentSidebar docs={docs} activeDoc={activeDoc} onSelectDoc={onSelectDoc} />
      <div>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
          <div style={{ fontSize: 13, color: "#4B5563", maxWidth: 560 }}>
            문서함에서 선택한 문서의 문단(섹션) 단위 분류 산출물과 <strong style={{ color: "#111827", fontWeight: 600 }}>{persona?.name} (C{persona?.clearance} · {persona?.department ?? "미인증"})</strong> 기준 판정입니다. 행을 누르면 문서 뷰어로 이동합니다.
          </div>
          <ModeLegend />
        </div>
        {activeDoc ? (
          <div className="dk-card" style={{ overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid #F3F4F6" }}>
            <FileText size={16} color="#6B7280" />
            <span style={{ fontSize: 14, fontWeight: 600, color: "#111827", letterSpacing: "-0.02em" }}>{activeDoc.doc_title}</span>
            <span style={{ padding: "1px 8px", borderRadius: 5, fontSize: 11, fontWeight: 500, background: "#F3F4F6", color: "#4B5563" }}>{activeDoc.dept_label}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: cols, columnGap: 16, padding: "8px 16px", fontSize: 11, fontWeight: 600, color: "#9CA3AF", borderBottom: "1px solid #F3F4F6", background: "#F9FAFB" }}>
            <div>데이터 원문</div><div>요약 (A2 일반화)</div><div>키워드</div><div>보안 등급</div>
          </div>
          {activeDoc.sections.map((sec) => (
            <div key={sec.id} onClick={() => onOpen(activeDoc.doc, sec.id)}
              style={{ display: "grid", gridTemplateColumns: cols, columnGap: 16, padding: "14px 16px", borderBottom: "1px solid #F3F4F6", cursor: "pointer", alignItems: "start", opacity: sec.kind === "blocked" ? 0.62 : 1 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: "#9CA3AF", marginBottom: 4, display: "flex", gap: 6, alignItems: "center" }}>
                  {sec.title}<ABadge mode={sec.mode} />
                </div>
                <GridCellBody sec={sec} />
              </div>
              <div style={{ fontSize: 12.5, color: sec.mode === 2 ? "#111827" : "#4B5563", fontWeight: sec.mode === 2 ? 600 : 400 }}>{sec.summary}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignContent: "flex-start" }}>
                {sec.keywords.map((k) => (
                  <span key={k} style={{ padding: "1px 8px", borderRadius: 5, fontSize: 11, fontWeight: 500, border: "1px solid #E5E7EB", color: "#4B5563", whiteSpace: "nowrap" }}>{k}</span>
                ))}
              </div>
              <div><DBadge d={sec.d} /><div style={{ fontSize: 10.5, color: "#9CA3AF", marginTop: 3 }}>{sec.d_name}</div></div>
            </div>
          ))}
          </div>
        ) : (
          <div className="dk-card" style={{ padding: 24, color: "#9CA3AF", fontSize: 13 }}>표시할 문서가 없습니다.</div>
        )}
      </div>
    </div>
  );
}

function GridCellBody({ sec }: { sec: SectionView }) {
  if (sec.kind === "full" || sec.kind === "mask")
    return <div style={{ fontSize: 13, color: "#384252" }}><Segments segs={sec.segments ?? []} /></div>;
  if (sec.kind === "exposure")
    return (
      <div style={{ position: "relative" }}>
        <div style={{ filter: "blur(5px)", userSelect: "none", fontSize: 13, color: "#384252" }}>{sec.blur_text}</div>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}><AiBadge text="AI 추론 근거 전용" /></div>
      </div>
    );
  if (sec.kind === "semantic")
    return <div style={{ border: "1px dashed #D1D5DB", background: "#F9FAFB", borderRadius: 6, padding: "8px 12px", fontSize: 12.5, color: "#4B5563" }}>원문 비노출 — 일반화 요약으로 대체 제공</div>;
  return <div style={{ display: "flex", gap: 8, alignItems: "center", color: "#9CA3AF", fontSize: 13 }}><Lock size={14} /> 접근 차단 — 검색·목록에서 제외됩니다</div>;
}

/* ── 문서 뷰어 ───────────────────────────────────────── */
function ViewerView({ docs, activeDoc, persona, focusSec, onSelectDoc }: {
  docs: DocView[]; activeDoc: DocView | null; persona: Persona | null; focusSec: string | null; onSelectDoc: (doc: string) => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "264px minmax(0, 1fr)", gap: 20, alignItems: "start" }}>
      <DocumentSidebar docs={docs} activeDoc={activeDoc} onSelectDoc={onSelectDoc} />

      <div className="dk-card" style={{ padding: "20px 28px 8px" }}>
        {activeDoc && (
          <>
            <div style={{ paddingBottom: 14, borderBottom: "1px solid #F3F4F6" }}>
              <div style={{ fontSize: 19, fontWeight: 600, color: "#111827", letterSpacing: "-0.03em" }}>{activeDoc.doc_title}</div>
              <div style={{ fontSize: 12, color: "#9CA3AF", marginTop: 3 }}>{activeDoc.dept_label} · {activeDoc.sections.length}개 섹션 · <strong style={{ color: "#4B5563", fontWeight: 600 }}>{persona?.name} C{persona?.clearance}</strong> 기준 렌더링</div>
            </div>
            {activeDoc.sections.map((sec) => {
              const focused = sec.id === focusSec;
              return (
                <div key={sec.id} style={{ padding: focused ? "16px 12px" : "16px 0", borderBottom: "1px solid #F3F4F6", borderRadius: focused ? 8 : 0, background: focused ? "#F9FAFB" : "transparent", boxShadow: focused ? "inset 0 0 0 1px #E5E7EB" : "none" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: "#111827", letterSpacing: "-0.02em" }}>{sec.title}</span>
                    <DBadge d={sec.d} name={sec.d_name} />
                    <ABadge mode={sec.mode} />
                    <span style={{ fontSize: 11, color: "#9CA3AF" }}>{sec.reason}</span>
                  </div>
                  <ViewerSectionBody sec={sec} />
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

function ViewerSectionBody({ sec }: { sec: SectionView }) {
  if (sec.kind === "full")
    return <div style={{ fontSize: 13.5, color: "#384252" }}><Segments segs={sec.segments ?? []} /></div>;
  if (sec.kind === "mask")
    return (
      <>
        <div style={{ fontSize: 13.5, color: "#384252" }}><Segments segs={sec.segments ?? []} /></div>
        <div style={{ fontSize: 11.5, color: "#9CA3AF", marginTop: 6 }}>엔티티가 수집 시점 추출 목록 기준으로 플레이스홀더 치환되었습니다.</div>
      </>
    );
  if (sec.kind === "exposure")
    return (
      <div style={{ position: "relative" }}>
        <div style={{ filter: "blur(6px)", userSelect: "none", fontSize: 13.5, color: "#384252" }}>{sec.blur_text}</div>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}><AiBadge text="AI 추론 근거로만 사용 가능 — 직접 열람 불가" /></div>
      </div>
    );
  if (sec.kind === "semantic")
    return (
      <div style={{ background: "#F9FAFB", border: "1px solid #E5E7EB", borderRadius: 8, padding: "12px 16px" }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 11.5, fontWeight: 600, color: "#111827", marginBottom: 4 }}><Sparkles size={12} /> 일반화 요약 — 원문 비노출</div>
        <div style={{ fontSize: 13.5, color: "#384252" }}>{sec.summary}</div>
      </div>
    );
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "14px 16px", borderRadius: 8, background: "#F3F4F6", color: "#6B7280", fontSize: 13 }}>
      <Lock size={15} /> 이 섹션은 현재 등급에서 접근이 차단되었습니다. 실제 서비스에서는 검색·컨텍스트에서 제외됩니다.
    </div>
  );
}

/* ── 채팅 ─────────────────────────────────────────────── */
function ChatView({ persona, chat, loading, input, onInput, onSend, onSuggest }: {
  persona: Persona | null; chat: ChatMsg[]; loading: boolean; input: string;
  onInput: (v: string) => void; onSend: () => void; onSuggest: (q: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [chat, loading]);
  const botAvatar = (
    <div style={{ width: 30, height: 30, flex: "none", borderRadius: "50%", background: "#111827", color: "#FFFFFF", display: "flex", alignItems: "center", justifyContent: "center" }}><Sparkles size={14} /></div>
  );
  return (
    <div style={{ maxWidth: 820, margin: "0 auto", height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ flex: "none", display: "flex", gap: 8, alignItems: "center", padding: "2px 2px 12px" }}>
        <span style={{ display: "inline-flex", gap: 6, alignItems: "center", background: "#FFFFFF", border: "1px solid #E5E7EB", color: "#4B5563", borderRadius: 6, padding: "4px 12px", fontSize: 11.5 }}>
          <Info size={12} /> 페르소나를 전환하면 같은 질문의 답변이 등급에 맞게 다시 계산됩니다.
        </span>
      </div>
      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16, padding: "4px 2px" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
          {botAvatar}
          <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", padding: "11px 15px", borderRadius: "4px 12px 12px 12px", fontSize: 13.5, color: "#384252", maxWidth: "76%" }}>
            안녕하세요, DataKeeper 지식봇입니다. 아래 추천 질문을 선택하거나 직접 입력해보세요. 답변은 현재 페르소나 <strong style={{ color: "#111827", fontWeight: 600 }}>{persona?.name} (C{persona?.clearance})</strong>의 접근 등급에 맞게 판정됩니다.
          </div>
        </div>
        {chat.map((m) => (
          <div key={m.id} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "flex-end" }}>
              <div style={{ background: "#111827", color: "#FFFFFF", padding: "11px 15px", borderRadius: "12px 12px 4px 12px", maxWidth: "70%", fontSize: 13.5 }}>{m.q}</div>
              {persona && <img src={personaImg(persona.clearance)} alt="" style={{ width: 30, height: 30, borderRadius: "50%", flex: "none" }} />}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              {botAvatar}
              <div style={{ maxWidth: "76%", display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", padding: "11px 15px", borderRadius: "4px 12px 12px 12px", fontSize: 13.5, color: "#384252" }}>
                  <MarkdownAnswer>{m.answer}</MarkdownAnswer>
                </div>
                {m.sources.length > 0 && (
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: 11, color: "#9CA3AF", paddingLeft: 2 }}>
                    근거
                    {m.sources.slice(0, 3).map((s, i) => (
                      <span key={i} style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
                        <span style={{ padding: "1px 8px", borderRadius: 5, fontSize: 10.5, fontWeight: 500, background: "#F3F4F6", color: "#4B5563" }}>{s.title}</span>
                        <DBadge d={s.d} /><ABadge mode={s.mode} />
                      </span>
                    ))}
                  </div>
                )}
                {(m.guard?.blocked || m.guard?.triggered) && (
                  <div style={{ fontSize: 10.5, color: m.guard.blocked ? "#991B1B" : "#9A3412", paddingLeft: 2 }}>
                    출력 가드 {m.guard.blocked ? "차단" : "재생성"}{m.guard.leaked.length ? ` (${m.guard.leaked.join(", ")})` : ""}
                  </div>
                )}
                {m.fallback && <div style={{ fontSize: 10.5, color: "#9CA3AF", paddingLeft: 2 }}>LLM 키 없음 → 결정론적 조회 모드</div>}
              </div>
            </div>
          </div>
        ))}
        {loading && <div style={{ display: "flex", gap: 8, alignItems: "center" }}>{botAvatar}<span style={{ fontSize: 12.5, color: "#9CA3AF" }}>답변 판정 중…</span></div>}
      </div>
      <div style={{ flex: "none", display: "flex", gap: 6, flexWrap: "wrap", padding: "12px 0 10px" }}>
        {EXAMPLES.map((q) => (
          <div key={q} onClick={() => onSuggest(q)} style={{ display: "inline-flex", alignItems: "center", padding: "5px 12px", borderRadius: 6, border: "1px solid #D1D5DB", background: "#FFFFFF", color: "#111827", fontSize: 12.5, fontWeight: 500, cursor: "pointer" }}>{q}</div>
        ))}
      </div>
      <div style={{ flex: "none", display: "flex", gap: 8, alignItems: "center" }}>
        <input value={input} onChange={(e) => onInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") onSend(); }} placeholder="질문을 입력해보세요"
          style={{ flex: 1, height: 40, borderRadius: 8, border: "1px solid #D1D5DB", background: "#FFFFFF", padding: "0 14px", fontSize: 13.5, color: "#111827", outline: "none", fontFamily: "inherit", boxSizing: "border-box" }} />
        <button onClick={onSend} disabled={loading}
          style={{ height: 40, padding: "0 18px", flex: "none", borderRadius: 8, background: "#111827", color: "#FFFFFF", border: "none", cursor: loading ? "default" : "pointer", fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 6, opacity: loading ? 0.6 : 1 }}>
          <Send size={14} /> 보내기
        </button>
      </div>
    </div>
  );
}

/* ── 매트릭스 ────────────────────────────────────────── */
function MatrixView({ data, docs, activeDoc, personaId, onPick, onSelectDoc }: {
  data: { personas: Persona[]; rows: MatrixRow[] } | null; docs: DocView[]; activeDoc: DocView | null; personaId: string; onPick: (id: string) => void; onSelectDoc: (doc: string) => void;
}) {
  const rows = data?.rows.filter((row) => row.doc === activeDoc?.doc) ?? [];
  const cols = data ? `minmax(230px,1.4fr) repeat(${data.personas.length}, minmax(110px,1fr))` : "";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "264px minmax(0, 1fr)", gap: 20, alignItems: "start" }}>
      <DocumentSidebar docs={docs} activeDoc={activeDoc} onSelectDoc={onSelectDoc} />
      <div>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, marginBottom: 14, flexWrap: "wrap" }}>
          <div style={{ fontSize: 13, color: "#4B5563" }}>문서함에서 선택한 문서의 섹션 × 전 페르소나 판정 히트맵입니다. 열 머리글이나 셀을 누르면 해당 페르소나로 전환됩니다.</div>
          <ModeLegend />
        </div>
        {!data ? (
          <div className="dk-card" style={{ padding: 24, color: "#9CA3AF", fontSize: 13 }}>불러오는 중…</div>
        ) : (
          <div className="dk-card" style={{ overflow: "hidden" }}>
        {activeDoc && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid #F3F4F6" }}>
            <FileText size={16} color="#6B7280" />
            <span style={{ fontSize: 14, fontWeight: 600, color: "#111827", letterSpacing: "-0.02em" }}>{activeDoc.doc_title}</span>
            <span style={{ padding: "1px 8px", borderRadius: 5, fontSize: 11, fontWeight: 500, background: "#F3F4F6", color: "#4B5563" }}>{rows.length}개 섹션</span>
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: cols, background: "#F9FAFB" }}>
          <div style={{ padding: "12px 16px", fontSize: 11, fontWeight: 600, color: "#9CA3AF", borderBottom: "1px solid #F3F4F6", display: "flex", alignItems: "flex-end" }}>섹션 · 보안 등급</div>
          {data.personas.map((p) => (
            <div key={p.id} onClick={() => onPick(p.id)} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, padding: "12px 8px", cursor: "pointer", background: p.id === personaId ? "#F3F4F6" : "transparent", borderBottom: "1px solid #F3F4F6" }}>
              <img src={personaImg(p.clearance)} alt="" style={{ width: 34, height: 34, borderRadius: "50%" }} />
              <div style={{ fontSize: 12, fontWeight: 600, color: "#111827", whiteSpace: "nowrap" }}>{p.name}</div>
              <span style={cChip(false)}>C{p.clearance}</span>
            </div>
          ))}
        </div>
        {rows.map((row) => (
          <div key={row.id} style={{ display: "grid", gridTemplateColumns: cols, borderBottom: "1px solid #F3F4F6", alignItems: "center" }}>
            <div style={{ padding: "10px 16px" }}>
              <div style={{ fontSize: 10.5, color: "#9CA3AF" }}>{row.doc_title}</div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 2 }}>
                <span style={{ fontSize: 12.5, fontWeight: 600, color: "#111827" }}>{row.title}</span>
                <DBadge d={row.d} />
              </div>
            </div>
            {row.cells.map((c) => (
              <div key={c.persona_id} title={`${c.mode_name} — ${c.reason}`} onClick={() => onPick(c.persona_id)}
                style={{ display: "flex", justifyContent: "center", padding: "10px 8px", cursor: "pointer", alignSelf: "stretch", alignItems: "center", background: c.persona_id === personaId ? "#F9FAFB" : "transparent" }}>
                <span style={chip(MODES[c.mode])}>A{c.mode}</span>
              </div>
            ))}
          </div>
        ))}
        {rows.length === 0 && <div style={{ padding: 24, color: "#9CA3AF", fontSize: 13 }}>선택된 문서의 매트릭스 행이 없습니다.</div>}
          </div>
        )}
      </div>
    </div>
  );
}
