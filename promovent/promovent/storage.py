"""SQLite storage with ordered SQL migrations and an append-only audit log."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def migrate(self) -> list[int]:
        applied = []
        with self._lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            have = {r[0] for r in self.db.execute("SELECT version FROM schema_version")}
            for f in sorted(MIGRATIONS.glob("*.sql")):
                v = int(f.name.split("_")[0])
                if v in have:
                    continue
                self.db.executescript(f.read_text())
                self.db.execute("INSERT INTO schema_version VALUES (?, ?)", (v, utcnow()))
                applied.append(v)
            self.db.commit()
        return applied

    def audit(self, actor: str, action: str, detail: dict) -> None:
        with self._lock:
            self.db.execute("INSERT INTO audit_log (ts, actor, action, detail) VALUES (?,?,?,?)",
                            (utcnow(), actor, action, json.dumps(detail, default=str)))
            self.db.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, params)
            self.db.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, params)]
