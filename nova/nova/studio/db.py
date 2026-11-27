"""Persistent store (SQLite, WAL) with forward-only migrations.

Each call opens its own connection, so the API threads, the production worker and the
scheduler can share the database safely. Rows that hold structured data keep it as JSON text."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: core production entities
    """
    CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE ideas (id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), input TEXT NOT NULL,
        analysis TEXT, concepts TEXT, created_at TEXT NOT NULL);
    CREATE TABLE scripts (id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
        idea_id TEXT REFERENCES ideas(id), title TEXT, language TEXT, target_s REAL, created_at TEXT NOT NULL);
    CREATE TABLE script_versions (id TEXT PRIMARY KEY, script_id TEXT NOT NULL REFERENCES scripts(id),
        version INTEGER NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, operation TEXT, mode TEXT,
        analysis TEXT, est_duration_s REAL, created_at TEXT NOT NULL, UNIQUE(script_id, version));
    CREATE TABLE emotional_directions (script_version_id TEXT NOT NULL REFERENCES script_versions(id),
        sentence_index INTEGER NOT NULL, data TEXT NOT NULL, edited INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (script_version_id, sentence_index));
    CREATE TABLE productions (id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), idea TEXT,
        request TEXT NOT NULL, status TEXT NOT NULL, current_stage TEXT, error TEXT,
        script_version_id TEXT REFERENCES script_versions(id), idempotency_key TEXT UNIQUE,
        job_run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE production_stages (production_id TEXT NOT NULL REFERENCES productions(id), stage TEXT NOT NULL,
        status TEXT NOT NULL, output TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
        started_at TEXT, finished_at TEXT, PRIMARY KEY (production_id, stage));
    CREATE TABLE audio_assets (id TEXT PRIMARY KEY, production_id TEXT NOT NULL REFERENCES productions(id),
        format TEXT NOT NULL, path TEXT NOT NULL, bytes INTEGER, duration_s REAL, sample_rate INTEGER,
        sha256 TEXT, created_at TEXT NOT NULL);
    CREATE TABLE audio_segments (production_id TEXT NOT NULL REFERENCES productions(id), idx INTEGER NOT NULL,
        scene INTEGER, text TEXT, emotion TEXT, start_s REAL, end_s REAL, PRIMARY KEY (production_id, idx));
    CREATE TABLE subtitles (production_id TEXT NOT NULL REFERENCES productions(id), format TEXT NOT NULL,
        path TEXT NOT NULL, cues INTEGER, PRIMARY KEY (production_id, format));
    CREATE TABLE quality_reports (production_id TEXT PRIMARY KEY REFERENCES productions(id),
        passed INTEGER NOT NULL, report TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE production_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, production_id TEXT, ts TEXT NOT NULL,
        level TEXT NOT NULL, stage TEXT, message TEXT NOT NULL);
    CREATE INDEX idx_logs_prod ON production_logs(production_id);
    """,
    # 2: scheduling, calendar, learning
    """
    CREATE TABLE scheduled_jobs (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
        payload TEXT NOT NULL, schedule TEXT NOT NULL, timezone TEXT NOT NULL, next_run_utc TEXT,
        enabled INTEGER NOT NULL DEFAULT 1, priority INTEGER NOT NULL DEFAULT 5, max_retries INTEGER NOT NULL DEFAULT 1,
        depends_on TEXT REFERENCES scheduled_jobs(id), idempotency_key TEXT UNIQUE, lease_until TEXT,
        last_status TEXT, created_at TEXT NOT NULL);
    CREATE TABLE job_runs (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES scheduled_jobs(id),
        scheduled_for TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1, started_at TEXT, finished_at TEXT,
        status TEXT NOT NULL, production_id TEXT REFERENCES productions(id), error TEXT,
        UNIQUE(job_id, scheduled_for, attempt));
    CREATE TABLE content_calendar (id TEXT PRIMARY KEY, date TEXT NOT NULL, time TEXT, timezone TEXT NOT NULL,
        platform TEXT, category TEXT, title TEXT NOT NULL, theme TEXT, status TEXT NOT NULL DEFAULT 'idea',
        production_id TEXT REFERENCES productions(id), job_id TEXT REFERENCES scheduled_jobs(id), notes TEXT,
        created_at TEXT NOT NULL);
    CREATE TABLE notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL,
        message TEXT NOT NULL, production_id TEXT, job_id TEXT, read INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE user_preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL, source TEXT NOT NULL,
        updated_at TEXT NOT NULL);
    CREATE TABLE feedback (id TEXT PRIMARY KEY, production_id TEXT NOT NULL REFERENCES productions(id),
        rating INTEGER NOT NULL, comment TEXT, created_at TEXT NOT NULL);
    CREATE TABLE performance_metrics (id TEXT PRIMARY KEY, production_id TEXT REFERENCES productions(id),
        platform TEXT, metric TEXT NOT NULL, value REAL NOT NULL, observed_at TEXT NOT NULL, source TEXT NOT NULL);
    """,
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def dumps(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def loads(v):
    return json.loads(v) if v else None


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.migrate()

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
        finally:
            c.close()

    def migrate(self) -> int:
        with self._lock, self.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = c.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = row[0] or 0
            for v, sql in enumerate(MIGRATIONS, start=1):
                if v > current:
                    c.execute("BEGIN")
                    try:
                        for stmt in _statements(sql):
                            c.execute(stmt)
                        c.execute("INSERT INTO schema_version VALUES (?)", (v,))
                        c.execute("COMMIT")
                    except Exception:
                        c.execute("ROLLBACK")
                        raise
            return len(MIGRATIONS)

    def schema_version(self) -> int:
        with self.conn() as c:
            return c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    # --- tiny helpers -------------------------------------------------------------------
    def execute(self, sql: str, args: tuple = ()) -> int:
        with self.conn() as c:
            return c.execute(sql, args).rowcount

    def insert(self, table: str, row: dict) -> dict:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        vals = tuple(dumps(v) if isinstance(v, (dict, list)) else v for v in row.values())
        with self.conn() as c:
            c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", vals)
        return row

    def upsert(self, table: str, row: dict, keys: tuple[str, ...]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        sets = ", ".join(f"{k}=excluded.{k}" for k in row if k not in keys)
        vals = tuple(dumps(v) if isinstance(v, (dict, list)) else v for v in row.values())
        with self.conn() as c:
            c.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT ({', '.join(keys)}) "
                      f"DO UPDATE SET {sets}", vals)

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        with self.conn() as c:
            r = c.execute(sql, args).fetchone()
            return dict(r) if r else None

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def log(self, production_id: str | None, message: str, level: str = "info", stage: str | None = None) -> None:
        self.insert("production_logs", {"production_id": production_id, "ts": now(), "level": level,
                                        "stage": stage, "message": message[:4000]})

    def notify(self, message: str, level: str = "info", production_id: str | None = None,
               job_id: str | None = None) -> None:
        self.insert("notifications", {"ts": now(), "level": level, "message": message[:2000],
                                      "production_id": production_id, "job_id": job_id})


def _statements(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip()]
