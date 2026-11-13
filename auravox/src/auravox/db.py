"""Persistent production database (SQLite, WAL). Nothing important lives only in an agent's conversation memory.

Tables: jobs, tasks, voices, takes, models, engines, pronunciations, skills, prefs, events.
IDs: AVX-JOB-000001, AVX-TSK-000001, AVX-TAKE-000001.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT, priority INTEGER DEFAULT 50, status TEXT NOT NULL,
  payload TEXT, depends_on TEXT DEFAULT '[]', attempts INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 3,
  mem_mb INTEGER DEFAULT 300, scheduled_at REAL DEFAULT 0, lease_until REAL, worker TEXT,
  created REAL, started REAL, finished REAL, result TEXT, error TEXT, parent TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, job_id TEXT, agent TEXT, op TEXT, inputs TEXT, outputs TEXT, status TEXT,
  started REAL, finished REAL, log TEXT, error TEXT, evidence TEXT);
CREATE TABLE IF NOT EXISTS voices (
  voice_id TEXT PRIMARY KEY, character_id TEXT, name TEXT, profile TEXT, profile_sha TEXT, engine TEXT, model TEXT,
  model_version TEXT, status TEXT, approved_by TEXT, approved_at REAL, audition_take TEXT, created REAL);
CREATE TABLE IF NOT EXISTS takes (
  take_id TEXT PRIMARY KEY, job_id TEXT, line_id TEXT, voice_id TEXT, profile_sha TEXT, version INTEGER, kind TEXT,
  path TEXT, sha256 TEXT, settings TEXT, metrics TEXT, defects TEXT, score REAL, selected INTEGER DEFAULT 0,
  status TEXT, parent_take TEXT, created REAL);
CREATE TABLE IF NOT EXISTS models (
  key TEXT PRIMARY KEY, engine TEXT, path TEXT, config_path TEXT, sha256 TEXT, bytes INTEGER, license TEXT,
  status TEXT, installed_at REAL, meta TEXT);
CREATE TABLE IF NOT EXISTS engines (name TEXT PRIMARY KEY, status TEXT, detail TEXT, capabilities TEXT, checked_at REAL);
CREATE TABLE IF NOT EXISTS pronunciations (word TEXT, lang TEXT, respell TEXT, note TEXT, PRIMARY KEY (word, lang));
CREATE TABLE IF NOT EXISTS skills (
  name TEXT, target TEXT, path TEXT, source TEXT, provenance TEXT, status TEXT, backup TEXT, report TEXT, installed_at REAL,
  PRIMARY KEY (name, target));
CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, job_id TEXT, level TEXT, msg TEXT);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, priority, created);
CREATE INDEX IF NOT EXISTS takes_line ON takes(line_id, voice_id);
"""

JSON_COLS = {"payload", "depends_on", "result", "inputs", "outputs", "evidence", "profile", "settings", "metrics", "defects",
             "meta", "capabilities", "report", "value", "provenance"}


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.con = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=30000")
        self.con.executescript(SCHEMA)

    # ------------------------------------------------------------------ basics
    def x(self, sql: str, args=()):
        with self._lock:
            return self.con.execute(sql, args)

    def q(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [self._row(r) for r in self.con.execute(sql, args).fetchall()]

    def one(self, sql: str, args=()) -> dict | None:
        r = self.q(sql, args)
        return r[0] if r else None

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        for k in JSON_COLS & d.keys():
            if isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        return d

    def next_id(self, prefix: str) -> str:
        with self._lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                self.con.execute("INSERT OR IGNORE INTO counters VALUES (?, 0)", (prefix,))
                self.con.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (prefix,))
                n = self.con.execute("SELECT value FROM counters WHERE name = ?", (prefix,)).fetchone()[0]
                self.con.execute("COMMIT")
            except Exception:
                self.con.execute("ROLLBACK")
                raise
        return f"{prefix}-{n:06d}"

    def insert(self, table: str, row: dict) -> None:
        cols = list(row)
        vals = [json.dumps(v) if k in JSON_COLS and not isinstance(v, str) and v is not None else v for k, v in row.items()]
        self.x(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)

    def update(self, table: str, key: str, keyval, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = [json.dumps(v) if k in JSON_COLS and not isinstance(v, str) and v is not None else v for k, v in fields.items()]
        self.x(f"UPDATE {table} SET {sets} WHERE {key} = ?", vals + [keyval])

    def event(self, msg: str, job_id: str | None = None, level: str = "info") -> None:
        self.x("INSERT INTO events (at, job_id, level, msg) VALUES (?,?,?,?)", (time.time(), job_id, level, msg[:2000]))

    # ------------------------------------------------------------------ prefs / pronunciations
    def pref(self, key: str, default=None):
        r = self.one("SELECT value FROM prefs WHERE key = ?", (key,))
        return r["value"] if r else default

    def set_pref(self, key: str, value) -> None:
        self.insert("prefs", {"key": key, "value": value})

    def pronunciations(self, lang: str) -> dict[str, str]:
        return {r["word"]: r["respell"] for r in self.q("SELECT word, respell FROM pronunciations WHERE lang = ?", (lang,))}
