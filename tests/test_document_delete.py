#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app import store
from app.seed_db import seed
from app.server import app


def check(label: str, condition: bool) -> None:
    if not condition:
        print(f"[FAIL] {label}")
        raise SystemExit(1)
    print(f"[OK ] {label}")


def main() -> None:
    seed()
    client = TestClient(app)
    doc = "ai_sales_strategy_report"
    before_sections = store.sections_for_doc(doc)
    before_entities = sum(len(s["entities"]) for s in before_sections)

    res = client.delete(f"/api/documents/{doc}")
    check("삭제 API 200", res.status_code == 200 and res.json()["deleted"] == doc)
    check("문서 row 삭제", all(d["doc"] != doc for d in store.load_documents()))
    check("섹션 row 삭제", store.sections_for_doc(doc) == [])

    conn = store.get_conn()
    try:
        orphan_entities = conn.execute(
            "SELECT count(*) FROM entities WHERE section_id LIKE ?", (f"{doc}#%",)
        ).fetchone()[0]
    finally:
        conn.close()
    check("관련 엔티티 삭제", before_entities > 0 and orphan_entities == 0)

    missing = client.delete("/api/documents/not_found_doc")
    check("없는 문서 404", missing.status_code == 404)

    print("\n문서 삭제 테스트 통과 ✅")


if __name__ == "__main__":
    main()
