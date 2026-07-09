import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  getExternalStoreMessages,
  type AppendMessage,
  type ThreadMessageLike,
  useComposerRuntime,
  useAuiState,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import {
  ArrowDown,
  ArrowUp,
  Bot,
  CheckCircle2,
  Database,
  LockKeyhole,
  ShieldAlert,
  ShieldCheck,
  Square,
  UserRound,
} from "lucide-react";
import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";

type Persona = {
  id: string;
  name: string;
  clearance: number;
  department: string | null;
  channel: "internal" | "external";
};

type Guard = {
  triggered: boolean;
  leaked: string[];
  retried: boolean;
  blocked: boolean;
};

type SectionResult = {
  id: string;
  doc: string;
  doc_title: string;
  title: string;
  security_level: number;
  mode: number;
  mode_name: string;
  gap: number;
  reasons: string[];
  rendered: string;
  content_hidden: boolean;
  matched: string[];
};

type ChatMeta =
  | { kind: "chat"; used_sections: SectionResult[]; guard: Guard }
  | { kind: "search"; results: SectionResult[]; notice: string };

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta?: ChatMeta;
};

type RequestContext = {
  persona: Persona | null;
  purpose: "info" | "judgment";
};

const MODE_STYLE: Record<number, { tone: string; label: string }> = {
  0: { tone: "mode-open", label: "A0" },
  1: { tone: "mode-limited", label: "A1" },
  2: { tone: "mode-summary", label: "A2" },
  3: { tone: "mode-masked", label: "A3" },
  4: { tone: "mode-blocked", label: "A4" },
};

const EXAMPLES = [
  "논의 중인 고객사는 어디인가요",
  "인수 검토 중인 건이 있나요",
  "예상 계약 규모는 어느 정도인가요",
];

function nextId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function textFromAppend(message: AppendMessage) {
  return message.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

function convertMessage(message: ChatMessage): ThreadMessageLike {
  return {
    id: message.id,
    role: message.role,
    content: [{ type: "text", text: message.content }],
  };
}

function RuntimeProvider({
  context,
  children,
}: {
  context: RequestContext;
  children: ReactNode;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isRunning, setIsRunning] = useState(false);

  const askBackend = useCallback(
    async (question: string): Promise<ChatMessage> => {
      if (!context.persona) {
        return {
          id: nextId(),
          role: "assistant",
          content: "사용자 정보를 불러온 뒤 다시 질문해 주세요.",
        };
      }

      const payload = {
        persona_id: context.persona.id,
        question,
        purpose: context.purpose,
      };

      try {
        const data = await postJson<{
          answer: string;
          used_sections: SectionResult[];
          guard: Guard;
        }>("/api/chat", payload);
        return {
          id: nextId(),
          role: "assistant",
          content: data.answer,
          meta: {
            kind: "chat",
            used_sections: data.used_sections,
            guard: data.guard,
          },
        };
      } catch {
        const data = await postJson<{ results: SectionResult[] }>("/api/search", payload);
        return {
          id: nextId(),
          role: "assistant",
          content:
            data.results.length > 0
              ? "LLM 답변 모드를 사용할 수 없어 조회 모드로 전환했습니다."
              : "접근 권한 내에서 관련 정보를 찾지 못했습니다.",
          meta: {
            kind: "search",
            results: data.results,
            notice: "ANTHROPIC_API_KEY가 없거나 모델 호출에 실패해 결정론적 조회 결과를 표시합니다.",
          },
        };
      }
    },
    [context.persona, context.purpose],
  );

  const onNew = useCallback(
    async (message: AppendMessage) => {
      const input = textFromAppend(message);
      if (!input || isRunning) return;

      const userMessage: ChatMessage = { id: nextId(), role: "user", content: input };
      setMessages((prev) => [...prev, userMessage]);
      setIsRunning(true);
      try {
        const assistant = await askBackend(input);
        setMessages((prev) => [...prev, assistant]);
      } catch (error) {
        const detail = error instanceof Error ? error.message : "알 수 없는 오류";
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            content: `요청 처리에 실패했습니다. ${detail}`,
          },
        ]);
      } finally {
        setIsRunning(false);
      }
    },
    [askBackend, isRunning],
  );

  const runtime = useExternalStoreRuntime({
    isRunning,
    messages,
    convertMessage,
    onNew,
  });

  return <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>;
}

export function App() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [personaId, setPersonaId] = useState("sales_rep");
  const [purpose, setPurpose] = useState<"info" | "judgment">("info");

  useEffect(() => {
    fetch("/api/personas")
      .then((res) => res.json())
      .then((data: Persona[]) => {
        setPersonas(data);
        if (data.length && !data.some((p) => p.id === personaId)) {
          setPersonaId(data[0].id);
        }
      });
  }, [personaId]);

  const persona = useMemo(
    () => personas.find((p) => p.id === personaId) ?? personas[0] ?? null,
    [personaId, personas],
  );

  return (
    <RuntimeProvider context={{ persona, purpose }}>
      <div className="app-shell">
        <Header
          personas={personas}
          personaId={persona?.id ?? personaId}
          purpose={purpose}
          onPersonaChange={setPersonaId}
          onPurposeChange={setPurpose}
        />
        <main className="main-grid">
          <aside className="context-panel">
            <div className="panel-section">
              <div className="panel-label">현재 사용자</div>
              <div className="persona-card">
                <UserRound size={20} />
                <div>
                  <strong>{persona?.name ?? "불러오는 중"}</strong>
                  <span>
                    C{persona?.clearance ?? "-"} · {persona?.department ?? "외부 채널"}
                  </span>
                </div>
              </div>
            </div>
            <div className="panel-section">
              <div className="panel-label">질문 예시</div>
              <div className="example-list">
                {EXAMPLES.map((example) => (
                  <ComposerPreset key={example} text={example} />
                ))}
              </div>
            </div>
            <div className="panel-section note">
              <ShieldCheck size={18} />
              <p>답변 생성 전 검색 결과에 A모드를 적용하고 A4 섹션은 프롬프트에서 제외합니다.</p>
            </div>
          </aside>
          <Thread />
        </main>
      </div>
    </RuntimeProvider>
  );
}

function Header({
  personas,
  personaId,
  purpose,
  onPersonaChange,
  onPurposeChange,
}: {
  personas: Persona[];
  personaId: string;
  purpose: "info" | "judgment";
  onPersonaChange: (value: string) => void;
  onPurposeChange: (value: "info" | "judgment") => void;
}) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <LockKeyhole size={22} />
        </div>
        <div>
          <h1>DataKeeper</h1>
          <p>assistant-ui 기반 접근제어 챗</p>
        </div>
      </div>
      <div className="controls">
        <label>
          <span>사용자</span>
          <select value={personaId} onChange={(event) => onPersonaChange(event.target.value)}>
            {personas.map((persona) => (
              <option key={persona.id} value={persona.id}>
                {persona.name} · C{persona.clearance}
              </option>
            ))}
          </select>
        </label>
        <div className="segmented" role="group" aria-label="질의 목적">
          <button
            type="button"
            className={purpose === "info" ? "active" : ""}
            onClick={() => onPurposeChange("info")}
          >
            정보 조회
          </button>
          <button
            type="button"
            className={purpose === "judgment" ? "active" : ""}
            onClick={() => onPurposeChange("judgment")}
          >
            판단/집계
          </button>
        </div>
      </div>
    </header>
  );
}

function ComposerPreset({ text }: { text: string }) {
  const composer = useComposerRuntime();
  return (
    <button type="button" className="example-button" onClick={() => composer.setText(text)}>
      {text}
    </button>
  );
}

function Thread() {
  return (
    <section className="thread-card">
      <ThreadPrimitive.Root className="thread-root">
        <ThreadPrimitive.Viewport className="thread-viewport">
          <AuiIf condition={(state) => state.thread.isEmpty}>
            <Welcome />
          </AuiIf>
          <div className="message-list">
            <ThreadPrimitive.Messages>
              {({ message }) => <ThreadMessage role={message.role} />}
            </ThreadPrimitive.Messages>
          </div>
          <ThreadPrimitive.ViewportFooter className="thread-footer">
            <ThreadPrimitive.ScrollToBottom asChild>
              <button type="button" className="scroll-button" aria-label="아래로 이동">
                <ArrowDown size={16} />
              </button>
            </ThreadPrimitive.ScrollToBottom>
            <Composer />
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </section>
  );
}

function Welcome() {
  return (
    <div className="welcome">
      <Bot size={28} />
      <h2>접근 등급에 맞춰 답변합니다</h2>
      <p>Phase E는 `/api/chat`을 먼저 사용하고 실패하면 무-LLM 조회 모드로 폴백합니다.</p>
    </div>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root className="composer">
      <ComposerPrimitive.Input
        className="composer-input"
        placeholder="질문을 입력하세요"
        rows={1}
        autoFocus
      />
      <div className="composer-actions">
        <AuiIf condition={(state) => !state.thread.isRunning}>
          <ComposerPrimitive.Send asChild>
            <button type="button" className="send-button" aria-label="보내기">
              <ArrowUp size={18} />
            </button>
          </ComposerPrimitive.Send>
        </AuiIf>
        <AuiIf condition={(state) => state.thread.isRunning}>
          <ComposerPrimitive.Cancel asChild>
            <button type="button" className="send-button" aria-label="중지">
              <Square size={15} />
            </button>
          </ComposerPrimitive.Cancel>
        </AuiIf>
      </div>
    </ComposerPrimitive.Root>
  );
}

function ThreadMessage({ role }: { role: string }) {
  const originals = useAuiState((state) => getExternalStoreMessages(state.message)) as ChatMessage[];
  const message = originals[0];

  if (role === "user") {
    return (
      <MessagePrimitive.Root className="message-row user-row">
        <div className="user-bubble">
          <MessagePrimitive.Parts />
        </div>
      </MessagePrimitive.Root>
    );
  }

  return (
    <MessagePrimitive.Root className="message-row assistant-row">
      <div className="assistant-avatar">
        <Bot size={18} />
      </div>
      <div className="assistant-content">
        <div className="assistant-bubble">
          <MessagePrimitive.Parts />
        </div>
        {message?.meta ? <MessageMeta meta={message.meta} /> : null}
      </div>
    </MessagePrimitive.Root>
  );
}

function MessageMeta({ meta }: { meta: ChatMeta }) {
  const sections = meta.kind === "chat" ? meta.used_sections : meta.results;
  return (
    <div className="evidence-panel">
      <div className="evidence-head">
        <div>
          <Database size={16} />
          <strong>{sections.length}개 근거 섹션</strong>
        </div>
        {meta.kind === "chat" ? <GuardBadge guard={meta.guard} /> : <FallbackBadge />}
      </div>
      {meta.kind === "search" ? <p className="fallback-note">{meta.notice}</p> : null}
      <div className="section-list">
        {sections.map((section) => (
          <SectionCard key={section.id} section={section} />
        ))}
      </div>
    </div>
  );
}

function GuardBadge({ guard }: { guard: Guard }) {
  if (guard.blocked) {
    return (
      <span className="guard-badge danger">
        <ShieldAlert size={14} /> 차단
      </span>
    );
  }
  if (guard.triggered) {
    return (
      <span className="guard-badge warn">
        <ShieldAlert size={14} /> 재생성
      </span>
    );
  }
  return (
    <span className="guard-badge ok">
      <CheckCircle2 size={14} /> 통과
    </span>
  );
}

function FallbackBadge() {
  return (
    <span className="guard-badge neutral">
      <Database size={14} /> 조회 모드
    </span>
  );
}

function SectionCard({ section }: { section: SectionResult }) {
  const mode = MODE_STYLE[section.mode] ?? MODE_STYLE[4];
  return (
    <article className={`section-card ${mode.tone}`}>
      <div className="section-card-head">
        <span className="level">D{section.security_level}</span>
        <span className="mode">{section.mode_name}</span>
        <strong>{section.title}</strong>
      </div>
      <div className="doc-title">{section.doc_title}</div>
      <p className={section.content_hidden ? "section-body hidden-body" : "section-body"}>
        {section.rendered}
      </p>
      <details>
        <summary>판정 근거</summary>
        <ul>
          {section.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </details>
    </article>
  );
}
