"""FastAPI 백엔드 — 접근제어 키워드 검색 챗 서비스.

  uvicorn app.server:app --reload --port 8000

엔드포인트:
  GET  /api/personas               페르소나 목록
  GET  /api/documents?persona_id=  문서 목록 + 페르소나별 lock 상태
  POST /api/search                 접근제어 키워드 검색 (무-LLM, P0 핵심)

접근 판정은 항상 engine.decide()를 경유한다 (판정에 LLM 미사용).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import retrieval, store
from app.engine import decide
from app.pipeline import load_policy

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "app" / "web"

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


@app.post("/api/search")
def search(req: SearchReq) -> dict:
    persona = _persona_or_404(req.persona_id)
    purpose = req.purpose if req.purpose in ("info", "judgment") else "info"
    results = retrieval.search(req.question, persona, POLICY, purpose)
    return {"persona": persona, "purpose": purpose, "query": req.question, "results": results}


# 정적 프론트 서빙 (app/web). API 라우트 뒤에 마운트해야 /api/* 가 우선한다.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
