-- DataKeeper 챗 서비스 DB 스키마 (samples 전용)
-- app/seed_db.py 가 이 스키마로 datakeeper.db 를 생성·시딩한다.
-- 반환 필드는 기존 data/sections.json 항목 스키마와 호환된다 (engine/pipeline/store 재사용).

CREATE TABLE IF NOT EXISTS documents (
    doc         TEXT PRIMARY KEY,   -- 파일 stem (예: ai_sales_strategy_report)
    doc_title   TEXT NOT NULL,
    source_path TEXT NOT NULL       -- data/samples/xxx.md
);

CREATE TABLE IF NOT EXISTS sections (
    id                  TEXT PRIMARY KEY,   -- "<doc>#<index>"
    doc                 TEXT NOT NULL REFERENCES documents(doc),
    seq                 INTEGER NOT NULL,   -- 문서 내 순서
    title               TEXT NOT NULL,
    text                TEXT NOT NULL,
    security_level      INTEGER,            -- D0~D4, NULL=미분류(default-deny)
    confidence          REAL,
    needs_review        INTEGER NOT NULL DEFAULT 0,
    keywords            TEXT NOT NULL DEFAULT '[]',   -- JSON 배열
    departments         TEXT NOT NULL DEFAULT '[]',   -- JSON 배열 (부서 보정용)
    summary_generalized TEXT NOT NULL DEFAULT ''      -- A2용 일반화 요약
);

CREATE TABLE IF NOT EXISTS entities (
    section_id  TEXT NOT NULL REFERENCES sections(id),
    seq         INTEGER NOT NULL,           -- 섹션 내 순서 (마스킹 안정성)
    text        TEXT NOT NULL,              -- 원문 표기 (마스킹 대상)
    placeholder TEXT NOT NULL,              -- [고객사A] 등
    type        TEXT                        -- 고객사/금액/인명/일정 ...
);

CREATE TABLE IF NOT EXISTS personas (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    clearance   INTEGER NOT NULL,           -- C0~C4
    department  TEXT,
    channel     TEXT NOT NULL               -- internal | external
);

CREATE INDEX IF NOT EXISTS idx_sections_doc ON sections(doc);
CREATE INDEX IF NOT EXISTS idx_entities_section ON entities(section_id);
