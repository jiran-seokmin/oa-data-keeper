import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  Edit3,
  Eye,
  EyeOff,
  FileText,
  Info,
  LoaderCircle,
  Lock,
  MessageSquare,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";

type Grade = "O" | "S" | "C";
type View = "classification" | "question" | "logs";
type LogTab = "classification" | "access";

type Persona = {
  id: string;
  name: string;
  access_grade: Grade;
  department?: string | null;
};

type Section = {
  id: string;
  title: string;
  grade: Grade | null;
  confidence: number;
  classification_status: string;
  classification_reason: string;
  summary: string;
  keywords: string[];
  departments: string[];
};

type SectionPreview = {
  id: string;
  doc: string;
  doc_title: string;
  title: string;
  content: string;
};

type Document = {
  doc: string;
  doc_title: string;
  document_grade: Grade | null;
  sections: Section[];
};

type Skill = {
  id?: string;
  name?: string;
  title?: string;
  description?: string;
  summary?: string;
  reason?: string;
  grade?: Grade;
  enabled?: boolean;
  keywords?: string[];
  triggers?: string[];
};

type Source = {
  id: string;
  docTitle: string;
  title: string;
  grade: Grade;
  summary?: string;
};

type ChatMessage = {
  id: string;
  question: string;
  answer: string;
  sources: Source[];
  personaName: string;
  accessGrade: Grade;
  failed?: boolean;
};

type StoredChatSession = {
  personaName: string;
  accessGrade: Grade;
  messages: ChatMessage[];
};

type ChatSessions = Record<string, StoredChatSession>;

type UploadState = {
  state: "working" | "success" | "error";
  filename: string;
  message: string;
};

type Notice = { state: "success" | "error"; message: string };
type LogRecord = Record<string, unknown>;

const GRADES: Record<Grade, { name: string; description: string }> = {
  O: { name: "Open · 공개", description: "외부 공개 가능" },
  S: { name: "Sensitive · 민감", description: "조직 내부 제한" },
  C: { name: "Classified · 기밀", description: "중대한 영향 정보" },
};
const RANK: Record<Grade, number> = { O: 0, S: 1, C: 2 };
const SUGGESTIONS = [
  "현재 논의 중인 고객사는 어디인가요?",
  "계약 검토에서 주의할 조건을 알려주세요.",
  "보안 점검 후속 조치는 무엇인가요?",
  "DataKeeper가 관리하는 정보는 무엇인가요?",
];
const CHAT_SESSIONS_STORAGE_PREFIX = "oa-data-keeper:chat-sessions:";
const CHAT_SESSIONS_STORAGE_KEY = `${CHAT_SESSIONS_STORAGE_PREFIX}v1`;
const CHAT_SESSION_GENERATION_STORAGE_KEY = "oa-data-keeper:chat-session-generation";
const CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX = "bootstrap:";
const CHAT_SESSION_CLEAR_GENERATION_PREFIX = "clear:";
const CHAT_SESSIONS_VERSION = 1;
const CHAT_SESSION_SYNC_INTERVAL_MS = 5_000;
const CHAT_SESSION_SYNC_TIMEOUT_MS = 4_000;
const MAX_CHAT_MESSAGES_PER_PERSONA = 50;
const MAX_CHAT_CONTEXT_QUESTIONS = 5;

const navItems: { id: View; label: string; icon: typeof Sparkles }[] = [
  { id: "classification", label: "분류·학습", icon: Sparkles },
  { id: "question", label: "권한 기반 질문", icon: MessageSquare },
  { id: "logs", label: "판정·접근 로그", icon: ClipboardList },
];

const isGrade = (value: unknown): value is Grade => value === "O" || value === "S" || value === "C";
const canAccess = (access: Grade, section: Grade) => RANK[section] <= RANK[access];
const isPending = (status: string) => {
  const value = status.toLowerCase();
  return value.includes("pending") || value.includes("review") || value.includes("대기") || value.includes("확인");
};
const nextId = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === "object" && value !== null && !Array.isArray(value)
);

function isStoredSource(value: unknown): value is Source {
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && typeof value.docTitle === "string"
    && typeof value.title === "string"
    && isGrade(value.grade)
    && (value.summary === undefined || typeof value.summary === "string");
}

function isStoredChatMessage(value: unknown): value is ChatMessage {
  if (!isRecord(value) || !Array.isArray(value.sources)) return false;
  return typeof value.id === "string"
    && typeof value.question === "string"
    && typeof value.answer === "string"
    && typeof value.personaName === "string"
    && isGrade(value.accessGrade)
    && (value.failed === undefined || typeof value.failed === "boolean")
    && value.sources.every(isStoredSource);
}

function loadChatSessions(): ChatSessions {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.sessionStorage.getItem(CHAT_SESSIONS_STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.version !== CHAT_SESSIONS_VERSION || !isRecord(parsed.sessions)) return {};

    const sessions: ChatSessions = {};
    for (const [personaId, value] of Object.entries(parsed.sessions)) {
      if (!personaId.trim() || !isRecord(value) || !isGrade(value.accessGrade)
        || typeof value.personaName !== "string" || !Array.isArray(value.messages)) continue;
      const messages = value.messages.filter(isStoredChatMessage).slice(-MAX_CHAT_MESSAGES_PER_PERSONA);
      if (messages.length) {
        sessions[personaId] = {
          personaName: value.personaName,
          accessGrade: value.accessGrade,
          messages,
        };
      }
    }
    return sessions;
  } catch {
    return {};
  }
}

function persistChatSessions(sessions: ChatSessions) {
  if (typeof window === "undefined") return;
  try {
    if (!Object.keys(sessions).length) {
      window.sessionStorage.removeItem(CHAT_SESSIONS_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(CHAT_SESSIONS_STORAGE_KEY, JSON.stringify({
      version: CHAT_SESSIONS_VERSION,
      sessions,
    }));
  } catch {
    // Storage can be unavailable or full; the in-memory sessions still work.
  }
}

function loadChatSessionGeneration(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(CHAT_SESSION_GENERATION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistChatSessionGeneration(generation: string) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(CHAT_SESSION_GENERATION_STORAGE_KEY, generation);
  } catch {
    // The in-memory generation still prevents duplicate synchronization.
  }
}

function clearPersistedChatSessions(generation: string) {
  if (typeof window === "undefined") return;
  try {
    const keys: string[] = [];
    for (let index = 0; index < window.sessionStorage.length; index += 1) {
      const key = window.sessionStorage.key(index);
      if (key?.startsWith(CHAT_SESSIONS_STORAGE_PREFIX)) keys.push(key);
    }
    for (const key of keys) window.sessionStorage.removeItem(key);
    persistChatSessionGeneration(generation);
  } catch {
    // The in-memory transcript is still cleared even if storage is unavailable.
  }
}

function statusLabel(status: string) {
  const value = status.toLowerCase();
  if (isPending(status)) return "확인 필요";
  if (value.includes("user") || value.includes("confirm") || value.includes("확정")) return "사용자 확정";
  if (value.includes("skill") || value.includes("learn")) return "Skill 반영";
  return "자동 판정";
}

function confidenceLabel(value: number) {
  if (!Number.isFinite(value)) return "-";
  return `${Math.round(Math.max(0, Math.min(100, value <= 1 ? value * 100 : value)))}%`;
}

function maxGrade(sections: Section[]): Grade | null {
  let highest: Grade | null = null;
  for (const section of sections) {
    if (isGrade(section.grade) && (highest === null || RANK[section.grade] > RANK[highest])) highest = section.grade;
  }
  return highest;
}

async function errorMessage(response: Response) {
  const text = await response.text();
  if (!text) return `${response.status} ${response.statusText}`;
  try {
    const json = JSON.parse(text) as { detail?: unknown };
    if (typeof json.detail === "string") return json.detail;
  } catch {
    // Return the useful raw response below.
  }
  return text;
}

async function request<T>(url: string, init?: RequestInit, timeout = 30_000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (!response.ok) throw new Error(await errorMessage(response));
    return await response.json() as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("요청 시간이 초과되었습니다.");
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function listFrom<T>(payload: unknown, keys: string[]): T[] {
  if (Array.isArray(payload)) return payload as T[];
  if (!payload || typeof payload !== "object") return [];
  const record = payload as Record<string, unknown>;
  for (const key of keys) if (Array.isArray(record[key])) return record[key] as T[];
  return [];
}

function textField(record: LogRecord, keys: string[], fallback = "") {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return fallback;
}

function gradeField(record: LogRecord, keys: string[]) {
  for (const key of keys) if (isGrade(record[key])) return record[key] as Grade;
  return null;
}

function timeLabel(value: string) {
  if (!value) return "시간 정보 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function GradeBadge({ grade, compact = false }: { grade: Grade | null | undefined; compact?: boolean }) {
  if (!isGrade(grade)) return <span className={`grade grade-unknown${compact ? " compact" : ""}`}><b>?</b>{!compact && <span>미정</span>}</span>;
  return <span className={`grade grade-${grade.toLowerCase()}${compact ? " compact" : ""}`}><b>{grade}</b>{!compact && <span>{GRADES[grade].name.split(" · ")[1]}</span>}</span>;
}

function Empty({ icon: Icon, title, description }: { icon: typeof FileText; title: string; description: string }) {
  return <div className="empty"><span><Icon size={21} /></span><b>{title}</b><p>{description}</p></div>;
}

export function App() {
  const [view, setView] = useState<View>("classification");
  const [docs, setDocs] = useState<Document[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [personaId, setPersonaId] = useState("");
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [loadingSkills, setLoadingSkills] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [upload, setUpload] = useState<UploadState | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [editing, setEditing] = useState<Section | null>(null);
  const [draftGrade, setDraftGrade] = useState<Grade>("O");
  const [draftReason, setDraftReason] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatSessions, setChatSessions] = useState<ChatSessions>(loadChatSessions);
  const [chatSessionReady, setChatSessionReady] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const chatSessionRef = useRef(0);
  const chatGenerationRef = useRef<string | null>(loadChatSessionGeneration());
  const [logTab, setLogTab] = useState<LogTab>("classification");
  const [classificationLogs, setClassificationLogs] = useState<LogRecord[]>([]);
  const [accessLogs, setAccessLogs] = useState<LogRecord[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsError, setLogsError] = useState<string | null>(null);

  const loadDocs = useCallback(async () => {
    setLoadingDocs(true);
    try {
      const data = await request<{ docs: Document[] }>("/api/classifications");
      const next = Array.isArray(data.docs) ? data.docs : [];
      setDocs(next);
      setSelectedDocId((current) => current && next.some((doc) => doc.doc === current) ? current : next[0]?.doc ?? null);
      setPageError(null);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "분류 결과를 불러오지 못했습니다.");
    } finally { setLoadingDocs(false); }
  }, []);

  const loadSkills = useCallback(async () => {
    setLoadingSkills(true);
    try {
      const data = await request<unknown>("/api/skills");
      setSkills(listFrom<Skill>(data, ["skills", "items"]).filter((skill) => skill.enabled !== false));
    } catch (error) {
      setPageError((current) => current ?? (error instanceof Error ? error.message : "Skill을 불러오지 못했습니다."));
    } finally { setLoadingSkills(false); }
  }, []);

  const loadPersonas = useCallback(async () => {
    try {
      const data = await request<unknown>("/api/personas");
      const next = listFrom<Persona>(data, ["personas", "items"]).filter((persona) => isGrade(persona.access_grade));
      setPersonas(next);
      setPersonaId((current) => current && next.some((persona) => persona.id === current) ? current : next[0]?.id ?? "");
    } catch (error) {
      setPageError((current) => current ?? (error instanceof Error ? error.message : "사용자 목록을 불러오지 못했습니다."));
    }
  }, []);

  const loadLogs = useCallback(async () => {
    setLogsLoading(true);
    setLogsError(null);
    try {
      const [classifications, access] = await Promise.all([
        request<unknown>("/api/logs/classification"), request<unknown>("/api/logs/access"),
      ]);
      setClassificationLogs(listFrom<LogRecord>(classifications, ["logs", "items", "classification_logs"]));
      setAccessLogs(listFrom<LogRecord>(access, ["logs", "items", "access_logs"]));
    } catch (error) {
      setLogsError(error instanceof Error ? error.message : "로그를 불러오지 못했습니다.");
    } finally { setLogsLoading(false); }
  }, []);

  useEffect(() => { void loadDocs(); void loadSkills(); void loadPersonas(); }, [loadDocs, loadPersonas, loadSkills]);
  useEffect(() => { if (view === "logs") void loadLogs(); }, [loadLogs, view]);
  useEffect(() => { persistChatSessions(chatSessions); }, [chatSessions]);
  useEffect(() => {
    let cancelled = false;
    let syncing = false;
    const synchronize = async () => {
      if (syncing) return;
      syncing = true;
      try {
        const data = await request<{ generation?: unknown }>(
          "/api/runtime/chat-session", undefined, CHAT_SESSION_SYNC_TIMEOUT_MS,
        );
        const generation = typeof data.generation === "string" ? data.generation.trim() : "";
        if (cancelled || !generation) return;
        if (generation === chatGenerationRef.current) {
          setChatSessionReady(true);
          return;
        }
        const storedGeneration = chatGenerationRef.current;
        const storedGenerationIsRecognized = storedGeneration?.startsWith(
          CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX,
        ) || storedGeneration?.startsWith(CHAT_SESSION_CLEAR_GENERATION_PREFIX);
        if (generation.startsWith(CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX)
          && (storedGeneration === null || !storedGenerationIsRecognized)) {
          chatGenerationRef.current = generation;
          persistChatSessionGeneration(generation);
          setChatSessionReady(true);
          return;
        }
        chatGenerationRef.current = generation;
        clearPersistedChatSessions(generation);
        chatSessionRef.current += 1;
        setChatSessions({});
        setChatInput("");
        setPendingQuestion(null);
        setChatLoading(false);
        setChatSessionReady(true);
      } catch {
        if (!cancelled) setChatSessionReady(false);
      } finally {
        syncing = false;
      }
    };
    const handleFocus = () => { void synchronize(); };
    const handleVisibility = () => {
      if (document.visibilityState === "visible") void synchronize();
    };
    void synchronize();
    const interval = window.setInterval(() => { void synchronize(); }, CHAT_SESSION_SYNC_INTERVAL_MS);
    window.addEventListener("focus", handleFocus);
    window.addEventListener("online", handleFocus);
    window.addEventListener("pageshow", handleFocus);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener("online", handleFocus);
      window.removeEventListener("pageshow", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);
  useEffect(() => {
    if (!personas.length) return;
    const currentPersonas = new Map(personas.map((item) => [item.id, item]));
    setChatSessions((current) => {
      let changed = false;
      const next: ChatSessions = {};
      for (const [storedPersonaId, session] of Object.entries(current)) {
        const currentPersona = currentPersonas.get(storedPersonaId);
        if (!currentPersona || session.personaName !== currentPersona.name
          || session.accessGrade !== currentPersona.access_grade) {
          changed = true;
          continue;
        }
        const messages = session.messages.filter((message) => (
          message.personaName === currentPersona.name
          && message.accessGrade === currentPersona.access_grade
          && message.sources.every((source) => canAccess(currentPersona.access_grade, source.grade))
        ));
        if (messages.length !== session.messages.length) changed = true;
        if (messages.length) next[storedPersonaId] = { ...session, messages };
        else changed = true;
      }
      return changed ? next : current;
    });
  }, [personas]);

  const selectedDoc = useMemo(() => docs.find((doc) => doc.doc === selectedDocId) ?? docs[0] ?? null, [docs, selectedDocId]);
  const persona = useMemo(() => personas.find((item) => item.id === personaId) ?? personas[0] ?? null, [personaId, personas]);
  const activeChatSession = persona ? chatSessions[persona.id] : undefined;
  const messages = chatSessionReady && persona && activeChatSession?.personaName === persona.name
    && activeChatSession.accessGrade === persona.access_grade ? activeChatSession.messages : [];
  const sections = useMemo(() => docs.reduce((sum, doc) => sum + doc.sections.length, 0), [docs]);
  const pending = useMemo(() => docs.reduce((sum, doc) => sum + doc.sections.filter((section) => isPending(section.classification_status)).length, 0), [docs]);

  function openEditor(section: Section) {
    setEditing(section);
    setDraftGrade(isGrade(section.grade) ? section.grade : "O");
    setDraftReason(section.classification_reason || "검토자가 분류 근거를 확인했습니다.");
  }

  async function saveClassification() {
    if (!editing || saving || !draftReason.trim()) return;
    setSaving(editing.id);
    try {
      await request(`/api/sections/${encodeURIComponent(editing.id)}/classification`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ grade: draftGrade, reason: draftReason.trim(), actor: "demo-reviewer" }),
      });
      await Promise.all([loadDocs(), loadSkills()]);
      setNotice({ state: "success", message: `${editing.title} 분류를 ${draftGrade} 등급으로 확정했습니다.` });
      setEditing(null);
    } catch (error) {
      setNotice({ state: "error", message: error instanceof Error ? error.message : "분류를 저장하지 못했습니다." });
    } finally { setSaving(null); }
  }

  const uploadDocument = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".txt") && !file.name.toLowerCase().endsWith(".md")) {
      setUpload({ state: "error", filename: file.name, message: ".txt 또는 .md 문서만 업로드할 수 있습니다." });
      return;
    }
    try {
      setUpload({ state: "working", filename: file.name, message: "섹션을 나누고 CSO 등급을 판정하고 있습니다." });
      const content = await file.text();
      const result = await request<{ doc?: string; document_grade?: Grade; pending_review?: number }>(
        "/api/documents/upload",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filename: file.name, content }) },
        120_000,
      );
      await Promise.all([loadDocs(), loadSkills()]);
      if (result.doc) setSelectedDocId(result.doc);
      const grade = isGrade(result.document_grade) ? ` · 문서 ${result.document_grade} 등급` : "";
      const review = typeof result.pending_review === "number" ? ` · 확인 필요 ${result.pending_review}개` : "";
      setUpload({ state: "success", filename: file.name, message: `자동 분류 완료${grade}${review}` });
    } catch (error) {
      setUpload({ state: "error", filename: file.name, message: error instanceof Error ? error.message : "업로드에 실패했습니다." });
    }
  }, [loadDocs, loadSkills]);

  const deleteDocument = useCallback(async (doc: Document) => {
    if (!window.confirm(`'${doc.doc_title}' 문서와 현재 섹션 분류를 삭제할까요?`)) return;
    setDeleting(doc.doc);
    try {
      await request(`/api/documents/${encodeURIComponent(doc.doc)}`, { method: "DELETE" });
      await loadDocs();
      setUpload(null);
      setNotice({ state: "success", message: `${doc.doc_title} 문서를 삭제했습니다.` });
    } catch (error) {
      setNotice({ state: "error", message: error instanceof Error ? error.message : "문서를 삭제하지 못했습니다." });
    } finally { setDeleting(null); }
  }, [loadDocs]);

  const appendChatMessage = useCallback((targetPersona: Persona, message: ChatMessage) => {
    setChatSessions((current) => {
      const stored = current[targetPersona.id];
      const previous = stored?.personaName === targetPersona.name
        && stored.accessGrade === targetPersona.access_grade ? stored.messages : [];
      return {
        ...current,
        [targetPersona.id]: {
          personaName: targetPersona.name,
          accessGrade: targetPersona.access_grade,
          messages: [...previous, message].slice(-MAX_CHAT_MESSAGES_PER_PERSONA),
        },
      };
    });
  }, []);

  const clearCurrentChat = useCallback(() => {
    if (!persona) return;
    chatSessionRef.current += 1;
    setChatSessions((current) => {
      if (!(persona.id in current)) return current;
      const next = { ...current };
      delete next[persona.id];
      return next;
    });
    setChatInput("");
    setPendingQuestion(null);
    setChatLoading(false);
  }, [persona]);

  function changePersona(nextPersonaId: string) {
    if (nextPersonaId === personaId) return;
    chatSessionRef.current += 1;
    setPersonaId(nextPersonaId);
    setChatInput("");
    setPendingQuestion(null);
    setChatLoading(false);
  }

  const sendQuestion = useCallback(async (raw: string) => {
    const question = raw.trim();
    if (!question || !persona || chatLoading || !chatSessionReady) return;
    const chatSession = chatSessionRef.current;
    const contextQuestions = messages
      .filter((message) => !message.failed)
      .slice(-MAX_CHAT_CONTEXT_QUESTIONS)
      .map((message) => message.question);
    setChatInput(""); setPendingQuestion(question); setChatLoading(true);
    try {
      const data = await request<Record<string, unknown>>(
        "/api/chat",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona_id: persona.id, question, context_questions: contextQuestions, chat_session_generation: chatGenerationRef.current }) },
        120_000,
      );
      if (chatSession !== chatSessionRef.current) return;
      const answer = typeof data.answer === "string" ? data.answer : "권한 범위에서 답변을 생성하지 못했습니다.";
      const rawSources = listFrom<Record<string, unknown>>(data.sources ?? data.used_sections ?? data.results, ["sources", "items", "results"]);
      const sources = rawSources.flatMap<Source>((source) => {
        if (!isGrade(source.grade) || !canAccess(persona.access_grade, source.grade)) return [];
        return [{
          id: typeof source.id === "string" ? source.id : nextId(),
          docTitle: typeof source.doc_title === "string" ? source.doc_title : "문서",
          title: typeof source.title === "string" ? source.title : "권한 확인 섹션",
          grade: source.grade,
          summary: typeof source.summary === "string" ? source.summary : undefined,
        }];
      });
      appendChatMessage(persona, { id: nextId(), question, answer, sources, personaName: persona.name, accessGrade: persona.access_grade });
    } catch (chatError) {
      if (chatSession !== chatSessionRef.current) return;
      try {
        const data = await request<{ results: Record<string, unknown>[] }>(
          "/api/search",
          { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona_id: persona.id, question, context_questions: contextQuestions, chat_session_generation: chatGenerationRef.current }) },
        );
        if (chatSession !== chatSessionRef.current) return;
        const sources = (Array.isArray(data.results) ? data.results : []).flatMap<Source>((source) => {
          if (!isGrade(source.grade) || !canAccess(persona.access_grade, source.grade)) return [];
          return [{
            id: typeof source.id === "string" ? source.id : nextId(),
            docTitle: typeof source.doc_title === "string" ? source.doc_title : "문서",
            title: typeof source.title === "string" ? source.title : "권한 확인 섹션",
            grade: source.grade,
            summary: typeof source.summary === "string" ? source.summary : undefined,
          }];
        });
        appendChatMessage(persona, {
          id: nextId(), question,
          answer: sources.length
            ? "생성형 답변을 사용할 수 없어 권한 기반 검색 결과를 표시합니다. 아래 섹션만 현재 사용자의 접근 범위에 포함됩니다."
            : "현재 접근 권한 안에서 관련 섹션을 찾지 못했습니다.",
          sources, personaName: persona.name, accessGrade: persona.access_grade,
        });
      } catch (searchError) {
        if (chatSession !== chatSessionRef.current) return;
        const message = searchError instanceof Error
          ? searchError.message
          : chatError instanceof Error ? chatError.message : "질문을 처리하지 못했습니다.";
        appendChatMessage(persona, {
          id: nextId(), question, answer: message,
          sources: [], personaName: persona.name, accessGrade: persona.access_grade, failed: true,
        });
      }
    } finally {
      if (chatSession === chatSessionRef.current) {
        setPendingQuestion(null);
        setChatLoading(false);
      }
    }
  }, [appendChatMessage, chatLoading, chatSessionReady, messages, persona]);

  return <div className="app-shell">
    <header className="topbar">
      <button className="brand" type="button" onClick={() => setView("classification")}><span><ShieldCheck size={19} /></span><b>Data<em>Keeper</em><small>CSO Classification &amp; Access</small></b></button>
      <nav>{navItems.map((item) => { const Icon = item.icon; return <button key={item.id} type="button" className={view === item.id ? "active" : ""} onClick={() => setView(item.id)}><Icon size={15} />{item.label}</button>; })}</nav>
      <div className="top-spacer" /><span className="mvp"><i />MVP 1차</span>
      {view === "question" && persona && <div className="current-user"><Avatar name={persona.name} /><span><b>{persona.name}</b><small>{persona.department ?? "공통 사용자"}</small></span><GradeBadge grade={persona.access_grade} compact /></div>}
    </header>

    {notice && <div className={`notice ${notice.state}`} role="status">{notice.state === "success" ? <CheckCircle2 size={16} /> : <Info size={16} />}<span>{notice.message}</span><button type="button" aria-label="닫기" onClick={() => setNotice(null)}><X size={14} /></button></div>}

    <main>
      {view === "classification" && <ClassificationPage
        docs={docs} selectedDoc={selectedDoc} skills={skills} sectionCount={sections} pendingCount={pending}
        loadingDocs={loadingDocs} loadingSkills={loadingSkills} error={pageError} upload={upload} deleting={deleting}
        editing={editing} draftGrade={draftGrade} draftReason={draftReason} saving={saving}
        onSelect={setSelectedDocId} onUpload={uploadDocument} onDelete={deleteDocument} onEdit={openEditor}
        onCancel={() => setEditing(null)} onGrade={setDraftGrade} onReason={setDraftReason} onSave={() => void saveClassification()}
        onRetry={() => { void loadDocs(); void loadSkills(); }}
      />}
      {view === "question" && <QuestionPage personas={personas} persona={persona} messages={messages} input={chatInput} pending={pendingQuestion} loading={chatLoading} sessionReady={chatSessionReady} onPersona={changePersona} onInput={setChatInput} onSend={() => void sendQuestion(chatInput)} onSuggest={(value) => void sendQuestion(value)} onClear={clearCurrentChat} />}
      {view === "logs" && <LogsPage tab={logTab} classification={classificationLogs} access={accessLogs} loading={logsLoading} error={logsError} onTab={setLogTab} onRefresh={() => void loadLogs()} />}
    </main>
  </div>;
}

function Avatar({ name, large = false }: { name: string; large?: boolean }) {
  return <span className={`avatar${large ? " large" : ""}`}>{name.slice(0, 1)}</span>;
}

function PageHeading({ eyebrow, title, description, children }: { eyebrow: string; title: string; description: string; children?: React.ReactNode }) {
  return <section className="page-heading"><div><small>{eyebrow}</small><h1>{title}</h1><p>{description}</p></div>{children}</section>;
}

function ClassificationPage(props: {
  docs: Document[]; selectedDoc: Document | null; skills: Skill[]; sectionCount: number; pendingCount: number;
  loadingDocs: boolean; loadingSkills: boolean; error: string | null; upload: UploadState | null; deleting: string | null;
  editing: Section | null; draftGrade: Grade; draftReason: string; saving: string | null;
  onSelect: (id: string) => void; onUpload: (file: File) => void; onDelete: (doc: Document) => void; onEdit: (section: Section) => void;
  onCancel: () => void; onGrade: (grade: Grade) => void; onReason: (reason: string) => void; onSave: () => void; onRetry: () => void;
}) {
  return <div className="page classification-page">
    <PageHeading eyebrow="CLASSIFICATION FLOW" title="자동 판정부터 학습까지" description="섹션마다 O·S·C 등급을 판정하고, 불확실한 결과는 사용자가 확정합니다. 수정 근거는 다음 판정에 쓰이는 Skill로 축적됩니다.">
      <div className="metrics"><Metric value={props.docs.length} label="분류 문서" /><Metric value={props.sectionCount} label="전체 섹션" /><Metric value={props.pendingCount} label="확인 필요" hot={props.pendingCount > 0} /><Metric value={props.skills.length} label="활성 Skill" /></div>
    </PageHeading>
    {props.error && <div className="inline-error"><Info size={16} /><span>{props.error}</span><button type="button" onClick={props.onRetry}><RefreshCw size={14} />다시 불러오기</button></div>}
    <div className="classification-layout">
      <DocumentRail docs={props.docs} selected={props.selectedDoc} loading={props.loadingDocs} upload={props.upload} deleting={props.deleting} onSelect={props.onSelect} onUpload={props.onUpload} onDelete={props.onDelete} />
      <section className="workspace">
        {props.loadingDocs && props.docs.length === 0 ? <div className="loading"><LoaderCircle size={18} />분류 결과를 불러오는 중입니다.</div> : props.selectedDoc ? <>
          <header className="document-heading"><span><FileText size={19} /></span><div><small>선택 문서</small><h2>{props.selectedDoc.doc_title}</h2></div><aside><small>문서 최고 등급</small><GradeBadge grade={isGrade(props.selectedDoc.document_grade) ? props.selectedDoc.document_grade : maxGrade(props.selectedDoc.sections)} /></aside></header>
          <div className="max-rule"><ShieldCheck size={15} />문서 등급은 섹션 중 최고 등급입니다. 하나의 섹션만 C여도 문서 전체는 C로 취급합니다.</div>
          <div className="section-list">{props.selectedDoc.sections.map((section, index) => <SectionCard key={section.id} section={section} index={index} editing={props.editing?.id === section.id} draftGrade={props.draftGrade} draftReason={props.draftReason} saving={props.saving === section.id} onEdit={() => props.onEdit(section)} onCancel={props.onCancel} onGrade={props.onGrade} onReason={props.onReason} onSave={props.onSave} />)}</div>
        </> : <Empty icon={FileText} title="분류된 문서가 없습니다" description="문서함에서 텍스트 또는 마크다운 문서를 업로드해주세요." />}
      </section>
      <SkillRail skills={props.skills} loading={props.loadingSkills} />
    </div>
  </div>;
}

function Metric({ value, label, hot = false }: { value: number; label: string; hot?: boolean }) {
  return <div className={hot ? "metric hot" : "metric"}><b>{value}</b><span>{label}</span></div>;
}

function DocumentRail({ docs, selected, loading, upload, deleting, onSelect, onUpload, onDelete }: { docs: Document[]; selected: Document | null; loading: boolean; upload: UploadState | null; deleting: string | null; onSelect: (id: string) => void; onUpload: (file: File) => void; onDelete: (doc: Document) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const pick = (files: FileList | null) => { const file = files?.[0]; if (file) onUpload(file); if (input.current) input.current.value = ""; };
  return <aside className="rail documents"><RailTitle title="문서함" meta={String(docs.length)} />
    <button type="button" className="upload-zone" onClick={() => input.current?.click()} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }} onDrop={(event) => { event.preventDefault(); pick(event.dataTransfer.files); }}><input ref={input} type="file" accept=".txt,.md,text/plain,text/markdown" onChange={(event) => pick(event.target.files)} /><i>{upload?.state === "working" ? <LoaderCircle size={17} /> : <UploadCloud size={17} />}</i><span><b>문서 추가</b><small>.txt, .md 드래그 앤 드롭</small></span></button>
    {upload && <div className={`upload-state ${upload.state}`}>{upload.state === "working" ? <LoaderCircle size={14} /> : upload.state === "success" ? <CheckCircle2 size={14} /> : <Info size={14} />}<span><b>{upload.filename}</b><small>{upload.message}</small></span></div>}
    <div className="document-list">{loading && docs.length === 0 && <div className="rail-loading"><LoaderCircle size={15} />불러오는 중</div>}{docs.map((doc) => {
      const review = doc.sections.filter((section) => isPending(section.classification_status)).length;
      return <div key={doc.doc} role="button" tabIndex={0} className={`document-item${selected?.doc === doc.doc ? " active" : ""}`} onClick={() => onSelect(doc.doc)} onKeyDown={(event) => { if (event.key === "Enter") onSelect(doc.doc); }}><FileText size={16} /><span><b>{doc.doc_title}</b><small>{doc.sections.length}개 섹션{review ? ` · 확인 ${review}` : " · 판정 완료"}</small></span><GradeBadge grade={isGrade(doc.document_grade) ? doc.document_grade : maxGrade(doc.sections)} compact /><button type="button" aria-label={`${doc.doc_title} 삭제`} onClick={(event) => { event.stopPropagation(); onDelete(doc); }}>{deleting === doc.doc ? <LoaderCircle size={13} /> : <Trash2 size={13} />}</button></div>;
    })}</div>
  </aside>;
}

function RailTitle({ title, meta }: { title: string; meta?: string }) { return <div className="rail-title"><b>{title}</b>{meta && <small>{meta}</small>}</div>; }

function SectionCard({ section, index, editing, draftGrade, draftReason, saving, onEdit, onCancel, onGrade, onReason, onSave }: { section: Section; index: number; editing: boolean; draftGrade: Grade; draftReason: string; saving: boolean; onEdit: () => void; onCancel: () => void; onGrade: (grade: Grade) => void; onReason: (reason: string) => void; onSave: () => void }) {
  const pending = isPending(section.classification_status);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewId = `section-preview-${encodeURIComponent(section.id)}`;

  async function loadPreview() {
    if (previewLoading) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const result = await request<{ section?: SectionPreview }>(
        `/api/review/sections/${encodeURIComponent(section.id)}/preview`,
        { cache: "no-store" },
      );
      if (!result.section || typeof result.section.content !== "string") {
        throw new Error("섹션 원문 응답이 올바르지 않습니다.");
      }
      setPreviewText(result.section.content);
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : "섹션 내용을 불러오지 못했습니다.");
    } finally {
      setPreviewLoading(false);
    }
  }

  function togglePreview() {
    if (previewOpen) {
      setPreviewOpen(false);
      return;
    }
    setPreviewOpen(true);
    if (previewText === null && !previewLoading) void loadPreview();
  }

  return <article className={`section-card${pending ? " pending" : ""}`}><span className="section-index">{String(index + 1).padStart(2, "0")}</span><div>
    <header className="section-heading"><div><small>섹션 분류</small><h3>{section.title}</h3></div><GradeBadge grade={section.grade} /><span className={`status${pending ? " pending" : ""}`}>{pending && <i />}{statusLabel(section.classification_status)}</span><button type="button" onClick={onEdit}><Edit3 size={14} />{pending ? "검토하기" : "수정"}</button></header>
    <div className="facts"><span><small>신뢰도</small><b>{confidenceLabel(section.confidence)}</b></span><span><small>담당 범위</small><b>{section.departments.length ? section.departments.join(" · ") : "전사"}</b></span><span><small>판정 근거</small><b>{section.classification_reason || "자동 판정 근거 없음"}</b></span></div>
    <div className="summary"><Sparkles size={14} /><span><small>섹션 요약</small>{section.summary || "요약이 아직 생성되지 않았습니다."}</span></div>
    <button type="button" className={`section-preview-toggle${previewOpen ? " active" : ""}`} aria-expanded={previewOpen} aria-controls={previewId} onClick={togglePreview}>{previewOpen ? <EyeOff size={14} /> : <Eye size={14} />}<span>{previewOpen ? "원문 접기" : "원문 보기"}</span><small>{previewOpen ? "섹션 원문을 닫습니다." : "분류 판단에 사용된 섹션 원문을 확인합니다."}</small></button>
    {previewOpen && <section id={previewId} className="section-preview" role="region" aria-label={`${section.title} 원문 미리 보기`}>
      <header><span><Eye size={14} /><b>섹션 내용 미리 보기</b></span>{previewText !== null && <small>{previewText.length.toLocaleString()}자</small>}</header>
      {previewLoading && <div className="preview-loading" role="status"><LoaderCircle size={15} />섹션 내용을 불러오는 중입니다.</div>}
      {previewError && <div className="preview-error" role="alert"><Info size={15} /><span>{previewError}</span><button type="button" onClick={() => void loadPreview()}><RefreshCw size={13} />다시 시도</button></div>}
      {!previewLoading && !previewError && previewText !== null && <div className="preview-content" tabIndex={0}>{previewText || "내용이 없는 섹션입니다."}</div>}
    </section>}
    {!!section.keywords.length && <div className="keywords">{section.keywords.map((keyword) => <span key={keyword}>{keyword}</span>)}</div>}
    {editing && <div className="review-editor"><header><b><Edit3 size={14} />사용자 확정 · 수정</b><small>이 결정의 근거는 다음 판정에 쓰이는 Skill로 학습됩니다.</small></header><div className="grade-picker">{(["O", "S", "C"] as Grade[]).map((grade) => <button key={grade} type="button" className={draftGrade === grade ? "active" : ""} onClick={() => onGrade(grade)}><GradeBadge grade={grade} compact /><span><b>{GRADES[grade].name}</b><small>{GRADES[grade].description}</small></span></button>)}</div><label><span>확정·수정 근거</span><textarea rows={2} value={draftReason} onChange={(event) => onReason(event.target.value)} placeholder="판정 근거를 입력해주세요." /></label><footer><button type="button" onClick={onCancel} disabled={saving}>취소</button><button type="button" className="primary" onClick={onSave} disabled={saving || !draftReason.trim()}>{saving ? <LoaderCircle size={14} /> : <CheckCircle2 size={14} />}등급 확정</button></footer></div>}
  </div></article>;
}

function SkillRail({ skills, loading }: { skills: Skill[]; loading: boolean }) {
  return <aside className="rail skills"><RailTitle title="학습된 Skill" meta={`${skills.length} 활성`} /><div className="skill-intro"><BookOpen size={17} /><span><b>사용자 피드백 자동 반영</b><small>확정·수정된 판단 근거가 다음 문서 분류에 적용됩니다.</small></span></div>{loading && <div className="rail-loading"><LoaderCircle size={15} />Skill 불러오는 중</div>}{!loading && !skills.length && <div className="skill-empty">아직 활성화된 Skill이 없습니다. 첫 분류를 확정하면 학습이 시작됩니다.</div>}<div className="skill-list">{skills.map((skill, index) => { const name = skill.name || skill.title || `분류 Skill ${index + 1}`; const description = skill.description || skill.summary || skill.reason || "사용자가 확정한 분류 근거"; const tags = skill.keywords ?? skill.triggers ?? []; return <article key={skill.id ?? `${name}-${index}`}><header><span><Sparkles size={13} />Enabled</span>{isGrade(skill.grade) && <GradeBadge grade={skill.grade} compact />}</header><h3>{name}</h3><p>{description}</p>{!!tags.length && <div>{tags.slice(0, 4).map((tag) => <small key={tag}>{tag}</small>)}</div>}</article>; })}</div></aside>;
}

function QuestionPage({ personas, persona, messages, input, pending, loading, sessionReady, onPersona, onInput, onSend, onSuggest, onClear }: { personas: Persona[]; persona: Persona | null; messages: ChatMessage[]; input: string; pending: string | null; loading: boolean; sessionReady: boolean; onPersona: (id: string) => void; onInput: (value: string) => void; onSend: () => void; onSuggest: (value: string) => void; onClear: () => void }) {
  const thread = useRef<HTMLDivElement>(null);
  useEffect(() => { if (thread.current) thread.current.scrollTop = thread.current.scrollHeight; }, [loading, messages, pending]);
  return <div className="page question-page"><PageHeading eyebrow="ACCESS-AWARE Q&A" title="권한 기반 질문" description="선택한 사용자의 접근 등급 안에 있는 섹션만 조회해 답변합니다. 권한 밖 섹션은 검색 단계부터 제외됩니다." />
    <div className="persona-picker"><b>질문 사용자</b>{personas.map((item) => <button key={item.id} type="button" className={item.id === persona?.id ? "active" : ""} onClick={() => onPersona(item.id)}><Avatar name={item.name} /><span><b>{item.name}</b><small>{item.department ?? "공통 사용자"}</small></span><GradeBadge grade={item.access_grade} compact /></button>)}</div>
    <div className="question-layout"><section className="chat-panel"><header><div><MessageSquare size={16} /><span><b>DataKeeper Assistant</b><small>현재 프로필의 대화와 후속 질문 문맥을 이 탭에서 기억</small></span></div>{!!(messages.length || pending) && <button type="button" onClick={onClear}>현재 대화 지우기</button>}</header><div ref={thread} className={`chat-thread${!messages.length && !pending ? " empty" : ""}`}>
      {!sessionReady ? <div className="welcome"><span><LoaderCircle size={22} /></span><h2>대화 세션을 확인하고 있습니다</h2><p>서버의 최신 초기화 상태를 확인한 뒤 현재 프로필의 대화를 표시합니다.</p></div> : !messages.length && !pending && <div className="welcome"><span><Search size={22} /></span><h2>{persona ? `${persona.name}의 권한으로 질문하세요` : "사용자를 선택해주세요"}</h2><p>{persona ? `${persona.access_grade} 등급까지 접근 가능한 섹션에서만 답을 찾습니다.` : "사용자별 O·S·C 접근 범위를 확인할 수 있습니다."}</p><div>{SUGGESTIONS.map((question) => <button key={question} type="button" onClick={() => onSuggest(question)}>{question}</button>)}</div></div>}
      {messages.map((message) => <div className="chat-turn" key={message.id}><div className="chat-row user"><div className="bubble user">{message.question}</div><Avatar name={message.personaName} /></div><div className="chat-row assistant"><span className="bot"><Sparkles size={15} /></span><div className="answer-stack"><div className={`bubble assistant${message.failed ? " error" : ""}`}><ReactMarkdown>{message.answer}</ReactMarkdown></div>{!!message.sources.length && <div className="sources"><b>사용 근거 {message.sources.length}</b>{message.sources.map((source) => <article key={`${message.id}-${source.id}`}><GradeBadge grade={source.grade} compact /><span><b>{source.docTitle} · {source.title}</b>{source.summary && <small>{source.summary}</small>}</span></article>)}</div>}<small className="answer-scope"><Lock size={11} />{message.personaName} · {message.accessGrade} 권한으로 조회</small></div></div></div>)}
      {pending && <div className="chat-turn"><div className="chat-row user"><div className="bubble user">{pending}</div><Avatar name={persona?.name ?? "사용자"} /></div><div className="chat-row assistant"><span className="bot"><Sparkles size={15} /></span><span className="thinking"><LoaderCircle size={14} />권한 확인 후 답변 생성 중</span></div></div>}
    </div><div className="composer"><textarea rows={2} value={input} disabled={!sessionReady} onChange={(event) => onInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); onSend(); } }} placeholder={sessionReady ? "접근 권한을 반영해 질문해보세요" : "대화 세션 확인 중"} /><div><span><Lock size={13} />{persona ? `${persona.access_grade} 권한` : "사용자 선택 필요"}</span><button type="button" aria-label="질문 보내기" onClick={onSend} disabled={!sessionReady || !persona || !input.trim() || loading}><ArrowUp size={17} /></button></div></div></section>
      <AccessPolicy persona={persona} />
    </div>
  </div>;
}

function AccessPolicy({ persona }: { persona: Persona | null }) {
  return <aside className="access-policy"><RailTitle title="현재 접근 정책" />{persona ? <><div className="access-user"><Avatar name={persona.name} large /><span><small>현재 사용자</small><b>{persona.name}</b><em>{persona.department ?? "공통 사용자"}</em></span><GradeBadge grade={persona.access_grade} /></div><div className="access-scale">{(["O", "S", "C"] as Grade[]).map((grade) => { const allowed = canAccess(persona.access_grade, grade); return <div key={grade} className={allowed ? "allowed" : "blocked"}><GradeBadge grade={grade} compact /><span><b>{GRADES[grade].name}</b><small>{allowed ? "조회 가능" : "조회 제외"}</small></span>{allowed ? <CheckCircle2 size={15} /> : <Lock size={14} />}</div>; })}</div><div className="policy-note"><Info size={14} /><span><b>원문 접근 원칙</b><small>허용된 섹션은 그대로 조회하고, 권한 밖 섹션은 검색·답변 컨텍스트에 넣지 않습니다.</small></span></div></> : <div className="skill-empty">질문 사용자를 선택하면 접근 가능한 등급을 표시합니다.</div>}</aside>;
}

function LogsPage({ tab, classification, access, loading, error, onTab, onRefresh }: { tab: LogTab; classification: LogRecord[]; access: LogRecord[]; loading: boolean; error: string | null; onTab: (tab: LogTab) => void; onRefresh: () => void }) {
  const rows = tab === "classification" ? classification : access;
  return <div className="page logs-page"><PageHeading eyebrow="AUDIT TRAIL" title="판정·접근 로그" description="등급이 결정된 과정과 권한 확인 결과를 기록합니다. 질문과 답변 내용 자체는 이 화면에 표시하지 않습니다."><button type="button" className="refresh" onClick={onRefresh} disabled={loading}><RefreshCw size={14} />새로고침</button></PageHeading>
    <div className="log-principles"><div><ClipboardList size={17} /><span><b>분류 결정 추적</b><small>자동 판정, 사용자 확정·수정, Skill 반영</small></span></div><div><ShieldCheck size={17} /><span><b>접근 사용 검증</b><small>사용자 권한과 실제 사용 섹션 확인</small></span></div><div><Lock size={17} /><span><b>내용 비기록</b><small>질문·답변 본문은 감사 화면에서 제외</small></span></div></div>
    <section className="log-card"><header><nav><button type="button" className={tab === "classification" ? "active" : ""} onClick={() => onTab("classification")}>등급 판정 로그 <span>{classification.length}</span></button><button type="button" className={tab === "access" ? "active" : ""} onClick={() => onTab("access")}>접근 로그 <span>{access.length}</span></button></nav><small><Lock size={12} />질문·답변 미표시</small></header>{error && <div className="inline-error inset"><Info size={16} />{error}</div>}{loading ? <div className="log-loading"><LoaderCircle size={18} />로그를 불러오는 중입니다.</div> : !rows.length ? <Empty icon={ClipboardList} title="기록된 로그가 없습니다" description="분류를 확정하거나 권한 기반 질문을 실행하면 감사 기록이 표시됩니다." /> : <div className="log-list">{tab === "classification" ? classification.map((row, index) => <ClassificationLog key={textField(row, ["id", "log_id"], String(index))} row={row} />) : access.map((row, index) => <AccessLog key={textField(row, ["id", "log_id"], String(index))} row={row} />)}</div>}</section>
  </div>;
}

function ClassificationLog({ row }: { row: LogRecord }) {
  const before = gradeField(row, ["previous_grade", "from_grade", "old_grade"]);
  const after = gradeField(row, ["new_grade", "to_grade", "grade"]);
  return <article className="log-row"><time><i />{timeLabel(textField(row, ["created_at", "timestamp", "occurred_at", "time"]))}</time><div><header><b>{textField(row, ["event_type", "action", "event"], "등급 판정")}</b><span>{textField(row, ["actor", "reviewer", "source"], "system")}</span></header><h3>{textField(row, ["doc_title", "document_title", "doc"], "문서")} <em>·</em> {textField(row, ["section_title", "title", "section_id"], "섹션")}</h3><p>{textField(row, ["reason", "classification_reason", "detail"], "판정 근거 기록")}</p></div><aside>{before && <GradeBadge grade={before} compact />}{before && after && <span>→</span>}{after ? <GradeBadge grade={after} compact /> : <small>등급 기록</small>}</aside></article>;
}

function AccessLog({ row }: { row: LogRecord }) {
  const grade = gradeField(row, ["access_grade"]);
  const result = textField(row, ["result", "decision", "status", "outcome"]);
  const value = row.allowed;
  const allowed = typeof value === "boolean" ? value : !result.toLowerCase().includes("den") && !result.includes("거부") && !result.includes("차단");
  const rawCount = row.allowed_count ?? row.used_section_count ?? row.authorized_section_count ?? row.section_count;
  const count = typeof rawCount === "number" ? rawCount : null;
  const rawBlocked = row.blocked_count;
  const blockedCount = typeof rawBlocked === "number" ? rawBlocked : null;
  return <article className="log-row"><time><i />{timeLabel(textField(row, ["created_at", "timestamp", "occurred_at", "time"]))}</time><div><header><b>{textField(row, ["persona_name", "user_name", "actor", "persona_id"], "사용자")}</b>{grade && <GradeBadge grade={grade} compact />}</header><h3>{textField(row, ["doc_title", "document_title", "doc"], "지식베이스")}</h3><p>{count === null ? "권한 범위 내 섹션 사용 여부 확인" : `허용 섹션 ${count}개 사용${blockedCount === null ? "" : ` · 권한 밖 ${blockedCount}개 제외`}`}</p></div><aside className={`access-result ${allowed ? "allowed" : "blocked"}`}>{allowed ? <CheckCircle2 size={14} /> : <Lock size={13} />}{result || textField(row, ["action"], allowed ? "권한 확인" : "접근 제외")}</aside></article>;
}
