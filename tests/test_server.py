"""FastAPI CSO contract smoke test on an isolated database."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import retrieval
from app.db import get_conn
from app.seed_db import seed
from app.server import app


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main() -> None:
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "server-test.db"
        seed(db_path=db_path)

        connection_factory = lambda: get_conn(db_path)
        with (
            patch("app.store.get_conn", side_effect=connection_factory),
            patch("app.governance.get_conn", side_effect=connection_factory),
        ):
            client = TestClient(app)
            personas = client.get("/api/personas")
            chat_session_state = client.get("/api/runtime/chat-session")
            classifications = client.get("/api/classifications")
            payload = classifications.json()

            check("사용자 API", personas.status_code == 200 and len(personas.json()) == 5)
            check("채팅 세션 무효화 세대 API", (
                chat_session_state.status_code == 200
                and isinstance(chat_session_state.json().get("generation"), str)
                and bool(chat_session_state.json()["generation"])
                and chat_session_state.headers.get("cache-control") == "no-store"
            ))
            check("분류 문서 API", classifications.status_code == 200 and len(payload["docs"]) == 3)
            first = payload["docs"][0]["sections"][0]
            check("분류 API는 원문 미노출", all(
                key not in section
                for document in payload["docs"]
                for section in document["sections"]
                for key in ("text", "content")
            ))

            preview = client.get(f"/api/review/sections/{quote(first['id'], safe='')}/preview")
            preview_section = preview.json()["section"]
            preview_conn = get_conn(db_path)
            try:
                expected_content = preview_conn.execute(
                    "SELECT text FROM sections WHERE id = ?", (first["id"],)
                ).fetchone()[0]
            finally:
                preview_conn.close()
            check(
                "선택 섹션 원문 미리보기 API",
                preview.status_code == 200
                and preview_section["id"] == first["id"]
                and preview_section["content"] == expected_content
                and "text" not in preview_section
                and preview.headers.get("cache-control") == "no-store",
            )
            review_queue = client.get("/api/review-queue").json()["sections"]
            check("검수 큐는 원문 미노출", all(
                key not in section
                for section in review_queue
                for key in ("text", "content")
            ))
            missing_preview = client.get("/api/review/sections/missing-section/preview")
            check("없는 섹션 미리보기 404", missing_preview.status_code == 404)

            update = client.patch(
                f"/api/sections/{quote(first['id'], safe='')}/classification",
                json={"grade": "O", "reason": "공개 가능한 안내 정보", "actor": "api-reviewer"},
            )
            check("등급 수정 API", update.status_code == 200 and
                  update.json()["section"]["grade"] == "O")
            check("등급 수정 응답은 원문 미노출", all(
                key not in update.json()["section"] for key in ("text", "content")
            ))
            check("수정 피드백 Skill 생성", update.json()["skill_action"] == "skill_created")
            skills = client.get("/api/skills").json()
            check("Skill 조회 API", skills["count"] == 1 and skills["skills"][0]["grade"] == "O")

            keyword = first["keywords"][0] if first["keywords"] else first["title"]
            search = client.post(
                "/api/search",
                json={"persona_id": "external", "question": keyword},
            )
            check("O 사용자 권한 검색", search.status_code == 200 and all(
                item["grade"] == "O" for item in search.json()["results"]
            ))
            follow_up = client.post(
                "/api/search",
                json={
                    "persona_id": "external",
                    "question": "그 내용은?",
                    "context_questions": [keyword],
                },
            )
            check("이전 질문 문맥을 사용하는 검색 API", (
                follow_up.status_code == 200 and bool(follow_up.json()["results"])
            ))
            too_much_context = client.post(
                "/api/search",
                json={
                    "persona_id": "external",
                    "question": keyword,
                    "context_questions": [keyword] * 6,
                },
            )
            check("검색 문맥은 최근 5개로 요청 제한", too_much_context.status_code == 422)

            classification_logs = client.get("/api/logs/classification").json()["logs"]
            access_logs = client.get("/api/logs/access").json()["logs"]
            check("분류·접근 로그 API", bool(classification_logs) and bool(access_logs))
            check("감사 응답에 질문·답변 필드 없음", all(
                key not in row
                for row in classification_logs + access_logs
                for key in ("question", "answer", "prompt", "content", "text")
            ))

            current_generation = chat_session_state.json()["generation"]
            before_conn = get_conn(db_path)
            try:
                access_count_before = before_conn.execute(
                    "SELECT COUNT(*) FROM access_logs"
                ).fetchone()[0]
            finally:
                before_conn.close()

            def rotate_generation_during_search(*args, **kwargs):
                rotate_conn = get_conn(db_path)
                try:
                    rotate_conn.execute(
                        "UPDATE runtime_state SET value = 'clear:server-test' "
                        "WHERE key = 'chat_session_generation'"
                    )
                    rotate_conn.commit()
                finally:
                    rotate_conn.close()
                return []

            with patch.object(retrieval, "search", side_effect=rotate_generation_during_search):
                stale_search = client.post(
                    "/api/search",
                    json={
                        "persona_id": "external",
                        "question": keyword,
                        "chat_session_generation": current_generation,
                    },
                )
            after_conn = get_conn(db_path)
            try:
                access_count_after = after_conn.execute(
                    "SELECT COUNT(*) FROM access_logs"
                ).fetchone()[0]
            finally:
                after_conn.close()
            check("처리 중 초기화된 세션은 409", stale_search.status_code == 409)
            check("초기화 뒤 이전 세션 접근 로그 미생성", (
                access_count_after == access_count_before
            ))

    print("\nFastAPI CSO 계약 테스트 통과 ✅")


if __name__ == "__main__":
    main()
