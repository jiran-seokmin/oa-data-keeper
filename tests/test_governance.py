"""Human confirmation -> reusable Skill -> content-free audit workflow test."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import governance, store, upload_pipeline
from app.db import get_conn, init_db
from app.engine import decide


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main() -> None:
    secret_text = "절대로 감사 로그나 Skill에 복사되면 안 되는 원문"
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "governance-test.db"
        conn = get_conn(db_path)
        try:
            init_db(conn)
            store.upsert_document(
                {"doc": "review", "doc_title": "검수 문서", "source_path": "test"},
                conn,
            )
            store.upsert_section(
                {
                    "id": "review#0",
                    "doc": "review",
                    "seq": 0,
                    "title": "계약 조건",
                    "text": secret_text,
                    "grade": "S",
                    "confidence": 0.62,
                    "classification_status": "pending_review",
                    "classification_reason": "낮은 자동 분류 신뢰도",
                    "summary": "계약 조건 요약",
                    "keywords": ["계약", "할인"],
                    "departments": ["영업팀"],
                },
                conn,
            )
            store.upsert_persona(
                {"id": "classified", "name": "기밀 사용자", "access_grade": "C"},
                conn,
            )

            before = store.get_section("review#0", conn)
            check("검수 대기는 최고 사용자도 기본 차단", not decide(
                before, {"access_grade": "C"}
            ).allowed)

            created = governance.confirm_and_learn(
                "review#0", "S", "내부 계약 조건이 포함됨", "security-admin", conn=conn
            )
            conn.commit()
            check("사람 확정 후 접근 가능", created["section"]["classification_status"] == "user_confirmed" and decide(
                created["section"], {"access_grade": "S"}
            ).allowed)
            check("피드백 Skill 자동 생성", created["skill_action"] == "skill_created")
            check("Skill이 다음 자동 분류 프롬프트에 반영", created["skill"]["name"] in
                  upload_pipeline._classification_system_prompt(conn))

            updated = governance.confirm_and_learn(
                "review#0", "C", "협상 전 기밀 할인율이 포함됨", "security-admin", conn=conn
            )
            conn.commit()
            skills = store.load_skills(conn)
            actions = list(reversed([
                log["action"] for log in store.load_classification_logs(conn)
            ]))
            check("재수정은 같은 Skill 갱신", updated["skill_action"] == "skill_updated" and len(skills) == 1)
            check("확정·Skill 생성·갱신 이력", actions == [
                "confirmed", "skill_created", "corrected", "skill_updated"
            ])

            store.log_access("classified", "search", ["review#0"], 0, doc="review", conn=conn)
            conn.commit()
            access_logs = store.load_access_logs(conn)
            classification_logs = store.load_classification_logs(conn)
            serialized_metadata = json.dumps(
                {"skills": skills, "access": access_logs, "classification": classification_logs},
                ensure_ascii=False,
            )
            check("Skill·감사 로그에 원문 미저장", secret_text not in serialized_metadata)

            forbidden = {"question", "answer", "prompt", "content", "text"}
            access_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(access_logs)").fetchall()
            }
            classification_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(classification_logs)").fetchall()
            }
            check("로그 스키마에 질의·답변·본문 열 없음", not forbidden & (
                access_columns | classification_columns
            ))
        finally:
            conn.close()

    print("\n분류 거버넌스 테스트 통과 ✅")


if __name__ == "__main__":
    main()
