"""FastAPI backend for the DataKeeper C/S/O MVP.

Classification list APIs expose review metadata, while the on-demand preview
endpoint returns source content for one explicitly selected review section.
User-facing search and chat read only confirmed sections permitted by the
caller's access grade. Audit records contain identifiers and decisions, never
questions, answers or source content.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import governance, pipeline, retrieval, store, upload_pipeline, views
from app.config import has_llm_credentials, llm_provider, load_dotenv
from app.db import get_chat_session_generation, init_db
from app.engine import GRADES, grade_rank


ROOT = Path(__file__).resolve().parent.parent
WEB_DIST_DIR = ROOT / "app" / "web" / "dist"

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize an empty DB or reject a legacy/unsupported schema at startup."""

    conn = store.get_conn()
    try:
        init_db(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="DataKeeper C/S/O", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


ContextQuestion = Annotated[str, Field(min_length=1, max_length=2000)]


class SearchReq(BaseModel):
    persona_id: str
    question: str = Field(min_length=1)
    context_questions: list[ContextQuestion] = Field(default_factory=list, max_length=5)
    chat_session_generation: str | None = Field(default=None, min_length=1, max_length=128)


class UploadReq(BaseModel):
    filename: str
    content: str


class ClassificationUpdateReq(BaseModel):
    grade: Literal["O", "S", "C"]
    reason: str = Field(min_length=1)
    actor: str = Field(default="reviewer", min_length=1)


class SkillUpdateReq(BaseModel):
    enabled: bool


def _persona_or_404(persona_id: str, conn=None) -> dict:
    persona = store.get_persona(persona_id, conn)
    if persona is None:
        raise HTTPException(status_code=404, detail=f"알 수 없는 사용자: {persona_id}")
    return persona


def _access_scope_counts(persona: dict, conn) -> tuple[int, int]:
    """Count allowed/blocked sections without reading section source text."""

    allowed_grades = GRADES[: grade_rank(persona["access_grade"]) + 1]
    placeholders = ",".join("?" for _ in allowed_grades)
    total = int(conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0])
    allowed = int(
        conn.execute(
            """SELECT COUNT(*) FROM sections
               WHERE classification_status IN ('auto_confirmed', 'user_confirmed')
               AND grade IN ("""
            + placeholders
            + ")",
            allowed_grades,
        ).fetchone()[0]
    )
    return allowed, total - allowed


def _single_doc(sections: list[dict]) -> str | None:
    docs = {section["doc"] for section in sections}
    return next(iter(docs)) if len(docs) == 1 else None


def _assert_chat_session_generation(requested: str | None, conn) -> None:
    if requested is not None and requested != get_chat_session_generation(conn):
        raise HTTPException(
            status_code=409,
            detail="채팅 세션이 초기화되었습니다. 최신 상태를 확인한 뒤 다시 질문해주세요.",
        )


def _record_session_access(
    req: SearchReq,
    persona: dict,
    action: str,
    sections: list[dict],
    blocked_count: int,
    conn,
) -> None:
    """Atomically reject stale sessions or append their access metadata."""

    conn.execute("BEGIN IMMEDIATE")
    try:
        _assert_chat_session_generation(req.chat_session_generation, conn)
        store.log_access(
            persona["id"],
            action,
            [section["id"] for section in sections],
            blocked_count,
            doc=_single_doc(sections),
            conn=conn,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@app.get("/api/personas")
def personas() -> list[dict]:
    return store.load_personas()


@app.get("/api/runtime/chat-session")
def chat_session_state(response: Response) -> dict:
    """Expose only the opaque generation used to invalidate local transcripts."""

    response.headers["Cache-Control"] = "no-store"
    conn = store.get_conn()
    try:
        return {"generation": get_chat_session_generation(conn)}
    finally:
        conn.close()


@app.get("/api/classifications")
def classifications() -> dict:
    """Return the complete content-free classification workbench."""

    conn = store.get_conn()
    try:
        documents = []
        for document in store.classification_docs(conn):
            sections = [
                views.classification_section_view(section)
                for section in store.sections_for_doc(document["doc"], conn)
            ]
            documents.append(
                {
                    "doc": document["doc"],
                    "doc_title": document["doc_title"],
                    "document_grade": document["grade"],
                    "section_count": document["section_count"],
                    "pending_review": document["pending_count"],
                    "confirmed_count": document["confirmed_count"],
                    "requires_review": document["requires_review"],
                    "sections": sections,
                }
            )
        return {"docs": documents}
    finally:
        conn.close()


@app.get("/api/review-queue")
def review_queue() -> dict:
    sections = [
        views.classification_section_view(section)
        for section in store.load_sections(classification_status="pending_review")
    ]
    return {"count": len(sections), "sections": sections}


@app.get("/api/review/sections/{section_id}/preview")
def section_preview(section_id: str, response: Response) -> dict:
    """Return one section's source text for the classification workbench."""

    response.headers["Cache-Control"] = "no-store"
    conn = store.get_conn()
    try:
        section = store.get_section(section_id, conn)
        if section is None:
            raise HTTPException(status_code=404, detail=f"섹션을 찾을 수 없습니다: {section_id}")
        return {"section": views.classification_section_preview(section)}
    finally:
        conn.close()


@app.patch("/api/sections/{section_id}/classification")
def update_classification(section_id: str, req: ClassificationUpdateReq) -> dict:
    try:
        result = governance.confirm_and_learn(
            section_id,
            req.grade,
            req.reason,
            req.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"섹션을 찾을 수 없습니다: {section_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "section": views.classification_section_view(result["section"]),
        "skill": result["skill"],
        "skill_action": result["skill_action"],
    }


@app.get("/api/skills")
def skills() -> dict:
    items = store.load_skills()
    return {"count": len(items), "skills": items}


@app.patch("/api/skills/{skill_id}")
def update_skill(skill_id: int, req: SkillUpdateReq) -> dict:
    try:
        return store.update_skill(skill_id, enabled=req.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Skill을 찾을 수 없습니다: {skill_id}") from exc


@app.get("/api/logs/classification")
def classification_logs(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    logs = store.load_classification_logs(limit=limit)
    return {"count": len(logs), "logs": logs}


@app.get("/api/logs/access")
def access_logs(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    logs = store.load_access_logs(limit=limit)
    return {"count": len(logs), "logs": logs}


@app.get("/api/documents")
def documents(persona_id: str) -> list[dict]:
    """Return only documents with at least one section visible to the user."""

    conn = store.get_conn()
    try:
        persona = _persona_or_404(persona_id, conn)
        output = []
        for document in store.load_documents(conn):
            visible = store.load_accessible_sections(persona, conn, doc=document["doc"])
            if not visible:
                continue
            visible_grade = max(
                (section["grade"] for section in visible),
                key=grade_rank,
            )
            output.append(
                {
                    "doc": document["doc"],
                    "doc_title": document["doc_title"],
                    "visible_grade": visible_grade,
                    "visible_section_count": len(visible),
                }
            )
        return output
    finally:
        conn.close()


@app.get("/api/sections")
def sections(persona_id: str) -> dict:
    """Return authorized section content only; denied metadata is not included."""

    conn = store.get_conn()
    try:
        persona = _persona_or_404(persona_id, conn)
        allowed = store.load_accessible_sections(persona, conn)
        documents: dict[str, dict] = {}
        for section in allowed:
            document = documents.setdefault(
                section["doc"],
                {
                    "doc": section["doc"],
                    "doc_title": section["doc_title"],
                    "sections": [],
                },
            )
            view = views.accessible_section_view(section, persona)
            if view is not None:
                document["sections"].append(view)
        store.log_access(
            persona["id"],
            "browse",
            [section["id"] for section in allowed],
            _access_scope_counts(persona, conn)[1],
            conn=conn,
        )
        conn.commit()
        return {"persona": persona, "docs": list(documents.values())}
    finally:
        conn.close()


@app.post("/api/search")
def search(req: SearchReq) -> dict:
    conn = store.get_conn()
    try:
        persona = _persona_or_404(req.persona_id, conn)
        _assert_chat_session_generation(req.chat_session_generation, conn)
        results = retrieval.search(
            req.question,
            persona,
            conn,
            context_questions=req.context_questions,
        )
        blocked_count = _access_scope_counts(persona, conn)[1]
        _record_session_access(req, persona, "search", results, blocked_count, conn)
        return {"persona": persona, "query": req.question, "results": results}
    finally:
        conn.close()


@app.post("/api/chat")
def chat(req: SearchReq) -> dict:
    if not has_llm_credentials():
        provider = llm_provider()
        key_name = (
            "GEMINI_API_KEY 또는 GOOGLE_API_KEY"
            if provider == "gemini"
            else "ANTHROPIC_API_KEY"
        )
        raise HTTPException(
            status_code=503,
            detail=f"{key_name}가 없어 LLM 답변 모드를 사용할 수 없습니다.",
        )

    conn = store.get_conn()
    try:
        persona = _persona_or_404(req.persona_id, conn)
        _assert_chat_session_generation(req.chat_session_generation, conn)
        try:
            result = pipeline.answer(
                req.question,
                persona,
                conn=conn,
                context_questions=req.context_questions,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"LLM 답변 생성 실패: {exc}") from exc
        blocked_count = _access_scope_counts(persona, conn)[1]
        _record_session_access(
            req, persona, "chat", result.used_sections, blocked_count, conn
        )
        return {
            "answer": result.answer,
            "used_sections": result.used_sections,
            "persona": result.persona,
            "query": result.question,
        }
    finally:
        conn.close()


@app.post("/api/documents/upload")
def upload_document(req: UploadReq) -> dict:
    filename = req.filename.strip()
    if not filename.lower().endswith((".txt", ".md")):
        raise HTTPException(status_code=400, detail=".txt 또는 .md 파일만 업로드할 수 있습니다.")
    try:
        return upload_pipeline.classify_and_store(filename, req.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"문서 분류 파이프라인 실패: {exc}") from exc


@app.delete("/api/documents/{doc}")
def delete_document(doc: str) -> dict:
    deleted = store.delete_document(doc)
    if deleted is None:
        raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {doc}")
    return {"deleted": deleted["doc"], "doc_title": deleted["doc_title"]}


# API routes must be registered before the static single-page application.
if WEB_DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST_DIR), html=True), name="web")
