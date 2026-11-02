import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from .migrations import migrate


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def unpack(row):
    if row is None:
        return None
    d = dict(row)
    for key in list(d):
        if key.endswith("_json"):
            d[key[:-5]] = json.loads(d.pop(key))
    return d


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
 selected_json TEXT NOT NULL DEFAULT '[]', viewed TEXT,
 preferences_json TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), ordinal INTEGER NOT NULL,
 name TEXT NOT NULL, original TEXT NOT NULL, thumbnail TEXT NOT NULL, base_preview TEXT NOT NULL,
 width INTEGER NOT NULL, height INTEGER NOT NULL, format TEXT NOT NULL,
 recipe_json TEXT NOT NULL, result TEXT, revision INTEGER NOT NULL DEFAULT 0,
 UNIQUE(project_id, ordinal)
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), request_id TEXT,
 role TEXT NOT NULL, content TEXT NOT NULL, operation_id TEXT,
 response_json TEXT, created_at TEXT NOT NULL,
 UNIQUE(project_id, request_id, role)
);
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), status TEXT NOT NULL,
 source_revision INTEGER NOT NULL, targets_json TEXT NOT NULL, summary TEXT NOT NULL,
 preview_asset_id TEXT, preview TEXT, error TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_items (
 operation_id TEXT NOT NULL REFERENCES operations(id), asset_id TEXT NOT NULL REFERENCES assets(id),
 source_revision INTEGER NOT NULL, recipe_json TEXT NOT NULL, status TEXT NOT NULL,
 result TEXT, error TEXT, PRIMARY KEY(operation_id, asset_id)
);
CREATE INDEX IF NOT EXISTS project_operations ON operations(project_id, created_at);
CREATE INDEX IF NOT EXISTS project_messages ON messages(project_id, created_at);
"""


class Database:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            existing = db.execute("SELECT 1 FROM sqlite_master WHERE name='projects'").fetchone()
            db.executescript(SCHEMA)
            migrate(db, path, bool(existing))
            db.execute(
                "UPDATE operations SET status='interrupted', error='服务已重启，请重试未完成的照片' WHERE status IN ('planning','previewing','queued','running')"
            )
            db.execute(
                "UPDATE operation_items SET status='interrupted' WHERE status IN ('queued','running')"
            )
            db.execute(
                "UPDATE messages SET response_json=? WHERE role='user' AND response_json IS NULL",
                (
                    dump(
                        {
                            "status": "interrupted",
                            "message": "上次请求已中断，请重新发送。",
                        }
                    ),
                ),
            )

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
