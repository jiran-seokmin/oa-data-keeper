"""FastAPI 백엔드 — 접근제어 키워드 검색 챗 서비스.

  uvicorn app.server:app --reload --port 8000

엔드포인트:
  GET  /api/personas               페르소나 목록
  GET  /api/documents?persona_id=  문서 목록 + 페르소나별 lock 상태
  POST /api/search                 접근제어 키워드 검색 (무-LLM, P0 핵심)
  POST /api/documents/upload       업로드 문서 Gemini 보안 등급 분류 + DB 추가
  DELETE /api/documents/{doc}       문서와 섹션 등급 메타데이터 삭제
  POST /api/chat                   Phase E LLM 답변 + 출력 가드 (키 없으면 503)

접근 판정은 항상 engine.decide()를 경유한다 (판정에 LLM 미사용).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import pipeline, retrieval, store, upload_pipeline, views
from app.config import has_llm_credentials, llm_provider, load_dotenv
from app.engine import MODE_NAMES, decide
from app.pipeline import load_policy

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST_DIR = ROOT / "app" / "web" / "dist"

load_dotenv()

app = FastAPI(title="DataKeeper 접근제어 챗")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

POLICY = load_policy()


class SearchReq(BaseModel):
    persona_id: str
    question: str
    purpose: str = "info"  # "info" | "judgment"


class UploadReq(BaseModel):
    filename: str
    content: str


def _persona_or_404(persona_id: str) -> dict:
    persona = store.get_persona(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail=f"알 수 없는 페르소나: {persona_id}")
    return persona


@app.get("/api/personas")
def personas() -> list[dict]:
    return store.load_personas()


@app.get("/api/documents")
def documents(persona_id: str) -> list[dict]:
    persona = _persona_or_404(persona_id)
    conn = store.get_conn()
    try:
        out = []
        for d in store.load_documents(conn):
            modes = [decide(s, persona, POLICY).mode for s in store.sections_for_doc(d["doc"], conn)]
            if modes and all(m == 4 for m in modes):
                lock = "locked"
            elif any(m > 0 for m in modes):
                lock = "partial"
            else:
                lock = "open"
            out.append({**d, "n_sections": len(modes), "lock_state": lock})
        return out
    finally:
        conn.close()


@app.post("/api/documents/upload")
def upload_document(req: UploadReq) -> dict:
    filename = req.filename.strip()
    if not filename.lower().endswith((".txt", ".md")):
        raise HTTPException(status_code=400, detail=".txt 또는 .md 파일만 업로드할 수 있습니다.")
    try:
        result = upload_pipeline.classify_and_store(filename, req.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"문서 분류 파이프라인 실패: {exc}") from exc
    return result


@app.delete("/api/documents/{doc}")
def delete_document(doc: str) -> dict:
    deleted = store.delete_document(doc)
    if deleted is None:
        raise HTTPException(status_code=404, detail=f"문서를 찾을 수 없습니다: {doc}")
    return {"deleted": deleted["doc"], "doc_title": deleted["doc_title"]}


@app.post("/api/search")
def search(req: SearchReq) -> dict:
    persona = _persona_or_404(req.persona_id)
    purpose = req.purpose if req.purpose in ("info", "judgment") else "info"
    results = retrieval.search(req.question, persona, POLICY, purpose)
    return {"persona": persona, "purpose": purpose, "query": req.question, "results": results}


@app.get("/api/sections")
def sections(persona_id: str) -> dict:
    """전 문서·전 섹션을 현재 페르소나 기준 판정한 뷰 (그리드·문서 뷰어용).

    시각화 목적이므로 A4(차단) 섹션도 잠금 상태로 포함한다. (실제 질의 경로인
    /api/search·/api/chat 은 A4를 완전히 제외한다.)
    """
    persona = _persona_or_404(persona_id)
    conn = store.get_conn()
    try:
        docs = []
        for d in store.load_documents(conn):
            secs = store.sections_for_doc(d["doc"], conn)
            depts = sorted({dep for s in secs for dep in s.get("departments", [])})
            docs.append({
                "doc": d["doc"],
                "doc_title": d["doc_title"],
                "dept_label": ", ".join(depts) if depts else "전사 공개",
                "sections": [views.section_view(s, decide(s, persona, POLICY)) for s in secs],
            })
        return {"persona": persona, "docs": docs}
    finally:
        conn.close()


@app.get("/api/matrix")
def matrix() -> dict:
    """전 섹션 × 전 페르소나 판정 히트맵."""
    personas = store.load_personas()
    conn = store.get_conn()
    try:
        rows = []
        for d in store.load_documents(conn):
            for s in store.sections_for_doc(d["doc"], conn):
                cells = []
                for p in personas:
                    dec = decide(s, p, POLICY)
                    cells.append({
                        "persona_id": p["id"], "mode": dec.mode,
                        "mode_name": MODE_NAMES[dec.mode], "reason": " · ".join(dec.reasons),
                    })
                rows.append({
                    "id": s["id"], "doc": d["doc"], "doc_title": d["doc_title"], "title": s["title"],
                    "d": s["security_level"], "cells": cells,
                })
        return {"personas": personas, "rows": rows}
    finally:
        conn.close()


@app.post("/api/chat")
def chat(req: SearchReq) -> dict:
    if not has_llm_credentials():
        provider = llm_provider()
        key_name = "GEMINI_API_KEY 또는 GOOGLE_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
        raise HTTPException(status_code=503, detail=f"{key_name}가 없어 LLM 답변 모드를 사용할 수 없습니다.")

    persona = _persona_or_404(req.persona_id)
    purpose = req.purpose if req.purpose in ("info", "judgment") else "info"
    try:
        result = pipeline.answer(req.question, persona, purpose, policy=POLICY)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LLM 답변 생성 실패: {exc}") from exc

    return {
        "answer": result.answer,
        "used_sections": result.used_sections,
        "guard": pipeline.guard_to_dict(result.guard),
        "persona": result.persona,
        "purpose": result.purpose,
        "query": result.question,
    }


# 정적 프론트 서빙 (app/web/dist). API 라우트 뒤에 마운트해야 /api/* 가 우선한다.
if WEB_DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST_DIR), html=True), name="web")
