"""Versioned, transactional additions. Existing image files are never rewritten."""

import sqlite3
from datetime import UTC, datetime

VERSION = 4


def migrate(db, path, existing):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > VERSION:
        raise RuntimeError("数据库来自更新版本，请使用对应版本的程序。")
    if version == VERSION:
        return
    if existing:
        directory = path.parent / "backups"
        directory.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        with sqlite3.connect(
            directory / f"before-v{2 if version < 2 else VERSION}-{stamp}.sqlite3"
        ) as backup:
            db.backup(backup)
    db.execute("BEGIN IMMEDIATE")
    if version < 2:
        db.execute("""CREATE TABLE luts (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
            original_filename TEXT NOT NULL, file_ref TEXT NOT NULL,
            sha256 TEXT NOT NULL, grid_size INTEGER NOT NULL,
            input_space TEXT NOT NULL, output_space TEXT NOT NULL,
            byte_size INTEGER NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(owner, sha256))""")
        db.execute("""CREATE TABLE personal_presets (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
            recipe_json TEXT NOT NULL, lut_id TEXT REFERENCES luts(id),
            revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, deleted_at TEXT)""")
        db.execute("""CREATE UNIQUE INDEX personal_presets_name
            ON personal_presets(owner, name) WHERE deleted_at IS NULL""")
        db.execute("""UPDATE operations SET status='stale',error='配方版本已升级，请重新生成预览。'
            WHERE status IN ('ready','previewing')""")
    if version < 3:
        for statement in AGENT_SCHEMA:
            db.execute(statement)
    if version < 4:
        for statement in LIBRARY_SCHEMA:
            db.execute(statement)
    db.execute(f"PRAGMA user_version={VERSION}")
    db.commit()


AGENT_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS agent_sessions (
        project_id TEXT PRIMARY KEY REFERENCES projects(id), epoch INTEGER NOT NULL DEFAULT 0,
        context_since TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_turns (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        request_id TEXT NOT NULL, instruction TEXT NOT NULL, expected_revision INTEGER NOT NULL,
        runtime_session TEXT NOT NULL UNIQUE, agent_id TEXT NOT NULL, epoch INTEGER NOT NULL,
        status TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', code TEXT,
        operation_id TEXT, runtime_id TEXT, tool_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, finished_at TEXT, expires_at REAL NOT NULL,
        UNIQUE(project_id, request_id))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS agent_active_project ON agent_turns(project_id)
        WHERE status IN ('queued','running')""",
    """CREATE TABLE IF NOT EXISTS tool_invocations (
        id TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES agent_turns(id),
        call_id TEXT NOT NULL, tool TEXT NOT NULL, action_key TEXT,
        payload_hash TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(turn_id,call_id), UNIQUE(turn_id,action_key))""",
]

LIBRARY_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS lut_profiles (
        lut_id TEXT PRIMARY KEY REFERENCES luts(id), revision INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1, compatibility TEXT NOT NULL DEFAULT 'unknown',
        metadata_json TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '{}',
        suggestions_json TEXT NOT NULL DEFAULT '{}', analysis_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS lut_index_jobs (
        id TEXT PRIMARY KEY, lut_id TEXT NOT NULL REFERENCES luts(id), owner TEXT NOT NULL,
        revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
        stage TEXT NOT NULL, error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS lut_active_job
        ON lut_index_jobs(lut_id,revision,fingerprint) WHERE status IN ('queued','running')""",
    "CREATE INDEX IF NOT EXISTS lut_job_history ON lut_index_jobs(lut_id,created_at)",
    """CREATE TABLE IF NOT EXISTS lut_embeddings (
        lut_id TEXT NOT NULL REFERENCES luts(id), fingerprint TEXT NOT NULL,
        revision INTEGER NOT NULL, text_hash TEXT NOT NULL, dimensions INTEGER NOT NULL,
        vector BLOB NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(lut_id,fingerprint))""",
    """CREATE TABLE IF NOT EXISTS lut_search_runs (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, project_id TEXT REFERENCES projects(id),
        project_revision INTEGER, result_json TEXT NOT NULL, created_at TEXT NOT NULL,
        expires_at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS lut_search_history ON lut_search_runs(owner,project_id,created_at)",
]
