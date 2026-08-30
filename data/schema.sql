-- DataKeeper CSO schema.
-- Grade order: O (Open) < S (Sensitive) < C (Classified · 기밀).
-- A document grade is derived from MAX(section.grade); it is never persisted.

CREATE TABLE IF NOT EXISTS documents (
    doc         TEXT PRIMARY KEY,
    doc_title   TEXT NOT NULL,
    source_path TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sections (
    id                    TEXT PRIMARY KEY,
    doc                   TEXT NOT NULL REFERENCES documents(doc) ON DELETE CASCADE,
    seq                   INTEGER NOT NULL CHECK (seq >= 0),
    title                 TEXT NOT NULL,
    parent_title          TEXT NOT NULL DEFAULT '',
    source_section_id     TEXT NOT NULL DEFAULT '',
    text                  TEXT NOT NULL,
    grade                 TEXT CHECK (grade IN ('O', 'S', 'C')),
    confidence            REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    classification_status TEXT NOT NULL DEFAULT 'pending_review'
                              CHECK (classification_status IN
                                     ('auto_confirmed', 'pending_review', 'user_confirmed')),
    classification_reason TEXT NOT NULL DEFAULT '',
    summary               TEXT NOT NULL DEFAULT '',
    keywords              TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(keywords)),
    departments           TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(departments)),
    confirmed_by          TEXT,
    confirmed_at          TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (doc, seq),
    CHECK (classification_status = 'pending_review' OR grade IS NOT NULL),
    CHECK (classification_status != 'user_confirmed'
           OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS personas (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    access_grade TEXT NOT NULL CHECK (access_grade IN ('O', 'S', 'C')),
    department   TEXT,
    channel      TEXT NOT NULL DEFAULT 'internal'
                         CHECK (channel IN ('internal', 'external')),
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Reusable, administrator-managed classification guidance.  The examples and
-- keyword fields contain classification metadata only, never source content.
CREATE TABLE IF NOT EXISTS classification_skills (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL,
    grade        TEXT CHECK (grade IN ('O', 'S', 'C')),
    keywords     TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(keywords)),
    examples     TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(examples)),
    enabled      INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_by   TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Classification audit events contain labels and reasons, never section text.
CREATE TABLE IF NOT EXISTS classification_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id      TEXT REFERENCES sections(id) ON DELETE SET NULL,
    doc             TEXT,
    action          TEXT NOT NULL,
    actor           TEXT,
    previous_grade  TEXT CHECK (previous_grade IN
                                ('O', 'S', 'C', 'D0', 'D1', 'D2', 'D3', 'D4')),
    new_grade       TEXT CHECK (new_grade IN ('O', 'S', 'C')),
    previous_status TEXT CHECK (previous_status IS NULL OR previous_status IN
                                ('auto_confirmed', 'pending_review', 'user_confirmed')),
    new_status      TEXT CHECK (new_status IS NULL OR new_status IN
                                ('auto_confirmed', 'pending_review', 'user_confirmed')),
    reason          TEXT NOT NULL DEFAULT '',
    confidence      REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    skill_id        INTEGER REFERENCES classification_skills(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Access logs intentionally omit question, answer, prompt and section content.
CREATE TABLE IF NOT EXISTS access_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id    TEXT REFERENCES personas(id) ON DELETE SET NULL,
    access_grade  TEXT CHECK (access_grade IN ('O', 'S', 'C')),
    action        TEXT NOT NULL,
    doc           TEXT,
    section_ids   TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(section_ids)),
    allowed_count INTEGER NOT NULL DEFAULT 0 CHECK (allowed_count >= 0),
    blocked_count INTEGER NOT NULL DEFAULT 0 CHECK (blocked_count >= 0),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Server-controlled generation used to invalidate browser-tab chat transcripts.
-- The transcripts themselves remain in sessionStorage and never enter SQLite.
CREATE TABLE IF NOT EXISTS runtime_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT OR IGNORE INTO runtime_state(key, value)
VALUES ('chat_session_generation', 'bootstrap:' || lower(hex(randomblob(16))));

CREATE INDEX IF NOT EXISTS idx_sections_doc ON sections(doc, seq);
CREATE INDEX IF NOT EXISTS idx_sections_grade_status ON sections(grade, classification_status);
CREATE INDEX IF NOT EXISTS idx_classification_logs_section ON classification_logs(section_id, created_at);
CREATE INDEX IF NOT EXISTS idx_classification_logs_doc ON classification_logs(doc, created_at);
CREATE INDEX IF NOT EXISTS idx_access_logs_persona ON access_logs(persona_id, created_at);
CREATE INDEX IF NOT EXISTS idx_access_logs_doc ON access_logs(doc, created_at);
CREATE INDEX IF NOT EXISTS idx_classification_skills_enabled ON classification_skills(enabled, name);

PRAGMA user_version = 3;
