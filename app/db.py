"""SQLite connection, schema initialization and legacy migration helpers."""

from __future__ import annotations

import secrets
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "datakeeper.db"
SCHEMA_PATH = ROOT / "data" / "schema.sql"
SCHEMA_VERSION = 3
CHAT_SESSION_GENERATION_KEY = "chat_session_generation"
CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX = "bootstrap:"
CLEAR_CHAT_SESSION_GENERATION_PREFIX = "clear:"

RUNTIME_DATA_COLUMNS = {
    "classification_skills": {
        "id", "name", "description", "instructions", "grade", "keywords",
        "examples", "enabled", "created_by", "created_at", "updated_at",
    },
    "classification_logs": {
        "id", "section_id", "doc", "action", "actor", "previous_grade",
        "new_grade", "previous_status", "new_status", "reason", "confidence",
        "skill_id", "created_at",
    },
    "access_logs": {
        "id", "persona_id", "access_grade", "action", "doc", "section_ids",
        "allowed_count", "blocked_count", "created_at",
    },
}
RUNTIME_DATA_TABLES = ("access_logs", "classification_logs", "classification_skills")
PRESERVED_DATA_TABLES = ("documents", "sections", "personas")
SUPPORTED_RUNTIME_DATA_SCHEMA_VERSIONS = {2, SCHEMA_VERSION}

CURRENT_CORE_COLUMNS = {
    "documents": {"doc", "doc_title", "source_path", "created_at", "updated_at"},
    "sections": {
        "id",
        "doc",
        "seq",
        "title",
        "parent_title",
        "source_section_id",
        "text",
        "grade",
        "confidence",
        "classification_status",
        "classification_reason",
        "summary",
        "keywords",
        "departments",
        "confirmed_by",
        "confirmed_at",
        "created_at",
        "updated_at",
    },
    "personas": {
        "id",
        "name",
        "access_grade",
        "department",
        "channel",
        "created_at",
        "updated_at",
    },
}

# FK-safe reset order. ``entities`` is included solely to clean legacy DBs.
TABLES = (
    "access_logs",
    "classification_logs",
    "classification_skills",
    "runtime_state",
    "entities",
    "sections",
    "documents",
    "personas",
)


class LegacySchemaError(RuntimeError):
    """Raised when a legacy database needs an explicit, backed-up migration."""


def get_conn(path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if table not in _table_names(conn):
        return set()
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def schema_state(conn: sqlite3.Connection) -> str:
    """Return ``empty``, ``legacy``, ``current`` or ``partial``."""

    tables = _table_names(conn)
    if not tables:
        return "empty"
    section_columns = _table_columns(conn, "sections")
    persona_columns = _table_columns(conn, "personas")
    if all(
        required <= _table_columns(conn, table)
        for table, required in CURRENT_CORE_COLUMNS.items()
    ):
        return "current"
    if "security_level" in section_columns and "clearance" in persona_columns:
        return "legacy"
    return "partial"


def init_db(conn: sqlite3.Connection, reset: bool = False) -> None:
    """Create the current schema.

    Legacy data is never modified implicitly. Call :func:`migrate_legacy_db`
    explicitly (normally with its default backup enabled), or use ``reset=True``
    only when intentionally replacing all data.
    """

    state = schema_state(conn)
    if not reset and state == "legacy":
        raise LegacySchemaError(
            "legacy D0-D4 database detected; call app.db.migrate_legacy_db() "
            "before starting the CSO application"
        )
    if not reset and state == "partial":
        raise RuntimeError("database schema is partial or unsupported; refusing implicit changes")

    if reset:
        for table in TABLES:
            conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.commit()

    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    if reset:
        conn.execute(
            "UPDATE runtime_state SET value = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE key = ?",
            (
                f"{CLEAR_CHAT_SESSION_GENERATION_PREFIX}{secrets.token_hex(16)}",
                CHAT_SESSION_GENERATION_KEY,
            ),
        )
    else:
        # Normalize the short-lived pre-release token format without treating
        # it as an intentional clear. Applied cleanup generations always use
        # the explicit ``clear:`` prefix.
        conn.execute(
            """UPDATE runtime_state
               SET value = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE key = ? AND value NOT LIKE ? AND value NOT LIKE ?""",
            (
                f"{CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX}{secrets.token_hex(16)}",
                CHAT_SESSION_GENERATION_KEY,
                f"{CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX}%",
                f"{CLEAR_CHAT_SESSION_GENERATION_PREFIX}%",
            ),
        )
    conn.commit()


def backup_database(
    path: str | Path = DB_PATH,
    destination: str | Path | None = None,
) -> Path:
    """Create a transactionally consistent SQLite backup without overwriting."""

    source_path = Path(path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if destination is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination_path = source_path.with_name(
            f"{source_path.stem}.backup-{stamp}{source_path.suffix or '.db'}"
        )
    else:
        destination_path = Path(destination).expanduser().resolve()
    if destination_path == source_path:
        raise ValueError("backup destination must differ from source database")
    if destination_path.exists():
        raise FileExistsError(destination_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(str(source_path), timeout=30)
    target = sqlite3.connect(str(destination_path), timeout=30)
    try:
        source.backup(target)
    except Exception:
        target.close()
        source.close()
        destination_path.unlink(missing_ok=True)
        raise
    else:
        target.close()
        source.close()
    shutil.copystat(source_path, destination_path)
    return destination_path


def _validate_runtime_data_schema(conn: sqlite3.Connection) -> None:
    """Reject databases whose deletion targets are not the expected CSO tables."""

    state = schema_state(conn)
    if state != "current":
        raise RuntimeError(
            f"current CSO database required; detected schema state: {state}"
        )
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version not in SUPPORTED_RUNTIME_DATA_SCHEMA_VERSIONS:
        raise RuntimeError(
            f"unsupported database schema version: {version}; "
            f"expected one of {sorted(SUPPORTED_RUNTIME_DATA_SCHEMA_VERSIONS)}"
        )
    for table, required_columns in RUNTIME_DATA_COLUMNS.items():
        missing = required_columns - _table_columns(conn, table)
        if missing:
            raise RuntimeError(
                f"{table} table is missing required columns: {sorted(missing)}"
            )


def runtime_data_counts(path: str | Path = DB_PATH) -> dict[str, int]:
    """Return deletion-target and preserved row counts without changing the DB."""

    db_path = Path(path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    conn = get_conn(db_path)
    try:
        _validate_runtime_data_schema(conn)
        return {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in (*RUNTIME_DATA_TABLES, *PRESERVED_DATA_TABLES)
        }
    finally:
        conn.close()


def get_chat_session_generation(conn: sqlite3.Connection) -> str:
    """Return the server generation that browser tabs use to invalidate chats."""

    try:
        row = conn.execute(
            "SELECT value FROM runtime_state WHERE key = ?",
            (CHAT_SESSION_GENERATION_KEY,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return f"{CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX}legacy"
        raise
    if row is None:
        return f"{CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX}legacy"
    generation = str(row[0])
    if generation.startswith((
        CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX,
        CLEAR_CHAT_SESSION_GENERATION_PREFIX,
    )):
        return generation
    return f"{CHAT_SESSION_BOOTSTRAP_GENERATION_PREFIX}legacy"


def clear_runtime_data(
    path: str | Path = DB_PATH,
    *,
    backup: bool | str | Path = True,
) -> dict:
    """Delete Skills and all audit logs, and invalidate every browser chat session.

    Documents, sections and personas are preserved. Database deletion and chat
    generation rotation occur in one transaction. A consistent backup is made
    before mutation unless explicitly disabled for a disposable database.
    """

    db_path = Path(path).expanduser().resolve()
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    backup_path: Path | None = None
    generation = f"{CLEAR_CHAT_SESSION_GENERATION_PREFIX}{secrets.token_hex(16)}"
    conn = get_conn(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _validate_runtime_data_schema(conn)
        before = {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in (*RUNTIME_DATA_TABLES, *PRESERVED_DATA_TABLES)
        }
        changes_before = conn.total_changes
        if backup:
            requested_path = None if backup is True else backup
            # This connection's RESERVED lock blocks writers while the backup
            # helper reads the last committed snapshot through another
            # connection. It prevents rows from appearing between backup and
            # deletion without trying to back up an uncommitted transaction.
            backup_path = backup_database(db_path, requested_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS runtime_state (
                   key TEXT PRIMARY KEY,
                   value TEXT NOT NULL,
                   updated_at TEXT NOT NULL DEFAULT
                       (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               )"""
        )
        for table in RUNTIME_DATA_TABLES:
            conn.execute(f'DELETE FROM "{table}"')
        conn.execute(
            """INSERT INTO runtime_state(key, value, updated_at)
               VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = excluded.updated_at""",
            (CHAT_SESSION_GENERATION_KEY, generation),
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        expected_changes = sum(before[table] for table in RUNTIME_DATA_TABLES) + 1
        actual_changes = conn.total_changes - changes_before
        if actual_changes != expected_changes:
            raise RuntimeError(
                "unexpected database side effects while clearing runtime data: "
                f"expected {expected_changes} row changes, observed {actual_changes}"
            )

        remaining = {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in RUNTIME_DATA_TABLES
        }
        if any(remaining.values()):
            raise RuntimeError(f"runtime rows remain after deletion: {remaining}")
        preserved = {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in PRESERVED_DATA_TABLES
        }
        expected_preserved = {table: before[table] for table in PRESERVED_DATA_TABLES}
        if preserved != expected_preserved:
            raise RuntimeError(
                f"preserved table counts changed: expected={expected_preserved}, actual={preserved}"
            )
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"foreign key validation failed: {foreign_key_errors}")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"database integrity check failed: {integrity}")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if backup_path is not None:
            raise RuntimeError(
                f"{exc}; recovery backup retained at: {backup_path}"
            ) from exc
        raise
    finally:
        conn.close()

    return {
        "database": str(db_path),
        "backup_path": str(backup_path) if backup_path else None,
        "deleted": {table: before[table] for table in RUNTIME_DATA_TABLES},
        "preserved": {table: before[table] for table in PRESERVED_DATA_TABLES},
        "chat_session_generation": generation,
    }


def _validate_legacy_schema(conn: sqlite3.Connection) -> None:
    required_sections = {
        "id",
        "doc",
        "seq",
        "title",
        "parent_title",
        "source_section_id",
        "text",
        "security_level",
        "confidence",
        "needs_review",
        "keywords",
        "departments",
        "summary_generalized",
    }
    required_documents = {"doc", "doc_title", "source_path"}
    required_personas = {"id", "name", "clearance", "department", "channel"}
    checks = {
        "sections": required_sections,
        "documents": required_documents,
        "personas": required_personas,
    }
    for table, required in checks.items():
        missing = required - _table_columns(conn, table)
        if missing:
            raise RuntimeError(f"legacy {table} table is missing required columns: {sorted(missing)}")


def migrate_legacy_db(
    path: str | Path = DB_PATH,
    *,
    backup: bool | str | Path = True,
) -> dict:
    """Migrate the D0-D4 schema to CSO while preserving core records.

    Mapping is intentionally conservative and fixed:

    - sections: D0 -> O, D1/D2/D3 -> S, D4 -> C
    - personas: C0 -> O, C1/C2/C3 -> S, C4 -> C
    - legacy ``needs_review`` or missing grade -> ``pending_review``
    - other classified rows -> ``auto_confirmed``

    Documents, sections and personas are copied in one transaction. Legacy
    entities are removed because the CSO model is binary allow/deny. A
    consistent backup is created by default before any schema mutation.
    """

    db_path = Path(path).expanduser().resolve()
    if not db_path.exists():
        conn = get_conn(db_path)
        try:
            init_db(conn)
        finally:
            conn.close()
        return {
            "migrated": False,
            "initialized": True,
            "backup_path": None,
            "documents": 0,
            "sections": 0,
            "personas": 0,
        }

    probe = get_conn(db_path)
    try:
        state = schema_state(probe)
        if state == "empty":
            init_db(probe)
            return {
                "migrated": False,
                "initialized": True,
                "backup_path": None,
                "documents": 0,
                "sections": 0,
                "personas": 0,
            }
        if state == "current":
            init_db(probe)
            counts = {
                "documents": probe.execute("SELECT count(*) FROM documents").fetchone()[0],
                "sections": probe.execute("SELECT count(*) FROM sections").fetchone()[0],
                "personas": probe.execute("SELECT count(*) FROM personas").fetchone()[0],
            }
            return {
                "migrated": False,
                "initialized": False,
                "backup_path": None,
                **counts,
            }
        if state != "legacy":
            raise RuntimeError(f"cannot migrate unsupported database schema state: {state}")
        _validate_legacy_schema(probe)
    finally:
        probe.close()

    backup_path: Path | None = None
    if backup:
        requested_path = None if backup is True else backup
        backup_path = backup_database(db_path, requested_path)

    conn = get_conn(db_path)
    try:
        has_entities = "entities" in _table_names(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        rename_script = """
BEGIN IMMEDIATE;
DROP INDEX IF EXISTS idx_sections_doc;
DROP INDEX IF EXISTS idx_entities_section;
ALTER TABLE documents RENAME TO legacy_documents;
ALTER TABLE sections RENAME TO legacy_sections;
ALTER TABLE personas RENAME TO legacy_personas;
"""
        if has_entities:
            rename_script += "ALTER TABLE entities RENAME TO legacy_entities;\n"
        conn.executescript(rename_script + SCHEMA_PATH.read_text(encoding="utf-8"))

        conn.execute(
            """INSERT INTO documents(doc, doc_title, source_path)
               SELECT doc, doc_title, source_path FROM legacy_documents"""
        )
        conn.execute(
            """INSERT INTO sections
               (id, doc, seq, title, parent_title, source_section_id, text, grade,
                confidence, classification_status, classification_reason, summary,
                keywords, departments, confirmed_by, confirmed_at)
               SELECT
                   id, doc, seq, title, parent_title, source_section_id, text,
                   CASE security_level
                       WHEN 0 THEN 'O'
                       WHEN 1 THEN 'S'
                       WHEN 2 THEN 'S'
                       WHEN 3 THEN 'S'
                       WHEN 4 THEN 'C'
                       ELSE NULL
                   END,
                   confidence,
                   CASE
                       WHEN security_level IS NULL OR COALESCE(needs_review, 0) != 0
                           THEN 'pending_review'
                       ELSE 'auto_confirmed'
                   END,
                   CASE
                       WHEN security_level IS NULL THEN 'Legacy migration: unclassified section'
                       ELSE 'Legacy migration from D' || security_level
                   END,
                   COALESCE(summary_generalized, ''),
                   COALESCE(keywords, '[]'),
                   COALESCE(departments, '[]'),
                   NULL,
                   NULL
               FROM legacy_sections"""
        )
        conn.execute(
            """INSERT INTO personas(id, name, access_grade, department, channel)
               SELECT id, name,
                   CASE clearance
                       WHEN 0 THEN 'O'
                       WHEN 1 THEN 'S'
                       WHEN 2 THEN 'S'
                       WHEN 3 THEN 'S'
                       WHEN 4 THEN 'C'
                   END,
                   department, COALESCE(channel, 'internal')
               FROM legacy_personas"""
        )
        conn.execute(
            """INSERT INTO classification_logs
               (section_id, doc, action, actor, previous_grade, new_grade,
                previous_status, new_status, reason, confidence)
               SELECT
                   id,
                   doc,
                   'legacy_migrated',
                   'system:migration',
                   CASE
                       WHEN security_level BETWEEN 0 AND 4 THEN 'D' || security_level
                       ELSE NULL
                   END,
                   CASE security_level
                       WHEN 0 THEN 'O'
                       WHEN 1 THEN 'S'
                       WHEN 2 THEN 'S'
                       WHEN 3 THEN 'S'
                       WHEN 4 THEN 'C'
                       ELSE NULL
                   END,
                   NULL,
                   CASE
                       WHEN security_level IS NULL OR COALESCE(needs_review, 0) != 0
                           THEN 'pending_review'
                       ELSE 'auto_confirmed'
                   END,
                   CASE
                       WHEN security_level IS NULL
                           THEN 'Legacy migration: unclassified section; default-deny'
                       WHEN COALESCE(needs_review, 0) != 0
                           THEN 'Legacy migration from D' || security_level || '; needs_review=1'
                       ELSE 'Legacy migration from D' || security_level
                   END,
                   confidence
               FROM legacy_sections"""
        )

        if has_entities:
            conn.execute("DROP TABLE legacy_entities")
        conn.execute("DROP TABLE legacy_sections")
        conn.execute("DROP TABLE legacy_documents")
        conn.execute("DROP TABLE legacy_personas")

        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"foreign key validation failed after migration: {foreign_key_errors}")

        counts = {
            "documents": conn.execute("SELECT count(*) FROM documents").fetchone()[0],
            "sections": conn.execute("SELECT count(*) FROM sections").fetchone()[0],
            "personas": conn.execute("SELECT count(*) FROM personas").fetchone()[0],
        }
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

    return {
        "migrated": True,
        "initialized": False,
        "backup_path": str(backup_path) if backup_path else None,
        **counts,
    }
