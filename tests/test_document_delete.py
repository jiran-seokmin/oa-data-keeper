"""Document deletion and content-free audit retention test."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import store
from app.db import get_conn
from app.seed_db import seed
from app.server import app


def check(label: str, condition: bool) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main() -> None:
    with TemporaryDirectory() as directory:
        db_path = Path(directory) / "delete-test.db"
        seed(db_path=db_path)
        doc = "enterprise_contract_negotiation"

        conn = get_conn(db_path)
        try:
            section_ids = [section["id"] for section in store.sections_for_doc(doc, conn)]
            before_logs = store.load_classification_logs(conn, doc=doc)
        finally:
            conn.close()

        with patch("app.store.get_conn", side_effect=lambda: get_conn(db_path)):
            client = TestClient(app)
            response = client.delete(f"/api/documents/{doc}")
            missing = client.delete("/api/documents/not_found_doc")

        check("삭제 API 200", response.status_code == 200 and response.json()["deleted"] == doc)
        check("없는 문서 404", missing.status_code == 404)

        conn = get_conn(db_path)
        try:
            check("문서 row 삭제", store.get_document(doc, conn) is None)
            check("관련 섹션 cascade 삭제", store.sections_for_doc(doc, conn) == [])
            retained_logs = store.load_classification_logs(conn, doc=doc)
            check("본문 없는 분류 이력 보존", len(retained_logs) == len(before_logs) > 0)
            check(
                "삭제된 섹션 FK는 NULL 처리",
                all(log["section_id"] is None for log in retained_logs),
            )
            check(
                "삭제된 ID가 원문 테이블에 없음",
                not conn.execute(
                    "SELECT 1 FROM sections WHERE id IN ({})".format(
                        ",".join("?" for _ in section_ids)
                    ),
                    section_ids,
                ).fetchone(),
            )
        finally:
            conn.close()

    print("\n문서 삭제 테스트 통과 ✅")


if __name__ == "__main__":
    main()
