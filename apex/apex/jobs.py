"""Persistent job queue on SQLite.

- Idempotency: enqueue with the same key returns the existing job instead of creating another.
- Leases: a claimed job holds a lease that the worker extends with heartbeats. If a worker dies,
  the lease expires and another claim recovers the job (RUNNING -> QUEUED -> RUNNING).
- Retries: retryable failures go RETRYING -> QUEUED with exponential backoff, up to max_attempts;
  after that the job is FAILED and stays in the table as a dead letter with its last error.
- Every state change is validated against ALLOWED_TRANSITIONS and recorded in job_events.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .models import ALLOWED_TRANSITIONS, JobState, TERMINAL_STATES

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  next_run_at REAL NOT NULL DEFAULT 0,
  lease_owner TEXT,
  lease_expires_at REAL,
  last_error TEXT,
  result TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  at REAL NOT NULL,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, next_run_at);
"""


class InvalidTransition(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    idempotency_key: str
    kind: str
    payload: dict
    state: JobState
    attempts: int
    max_attempts: int
    last_error: str | None
    result: dict | None


class JobQueue:
    def __init__(self, path: Path, clock=time.time, base_backoff: float = 30.0, max_backoff: float = 3600.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock, self.base_backoff, self.max_backoff = clock, base_backoff, max_backoff
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    # ---------------------------------------------------------------- helpers
    def _row(self, job_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return row

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(row["id"], row["idempotency_key"], row["kind"], json.loads(row["payload"]),
                   JobState(row["state"]), row["attempts"], row["max_attempts"], row["last_error"],
                   json.loads(row["result"]) if row["result"] else None)

    def _move(self, job_id: str, to: JobState, detail: str = "", **fields) -> None:
        """Validated state change inside the caller's transaction."""
        current = JobState(self._row(job_id)["state"])
        if to not in ALLOWED_TRANSITIONS[current]:
            raise InvalidTransition(f"{job_id}: {current.value} -> {to.value} is not allowed")
        sets = ", ".join(["state=?", "updated_at=?"] + [f"{k}=?" for k in fields])
        self.db.execute(f"UPDATE jobs SET {sets} WHERE id=?", (to.value, self.clock(), *fields.values(), job_id))
        self.db.execute("INSERT INTO job_events(job_id, from_state, to_state, at, detail) VALUES (?,?,?,?,?)",
                        (job_id, current.value, to.value, self.clock(), detail))

    # ---------------------------------------------------------------- API
    def enqueue(self, idempotency_key: str, kind: str, payload: dict, max_attempts: int = 3) -> Job:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if row is not None:
                self.db.execute("COMMIT")
                return self._job(row)
            job_id, now = uuid.uuid4().hex[:12], self.clock()
            self.db.execute("INSERT INTO jobs(id, idempotency_key, kind, payload, state, max_attempts, created_at, updated_at)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (job_id, idempotency_key, kind, json.dumps(payload), JobState.CREATED.value,
                             max_attempts, now, now))
            self.db.execute("INSERT INTO job_events(job_id, from_state, to_state, at, detail) VALUES (?,?,?,?,?)",
                            (job_id, None, JobState.CREATED.value, now, "created"))
            self._move(job_id, JobState.QUEUED, "enqueued")
            self.db.execute("COMMIT")
            return self.get(job_id)
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def get(self, job_id: str) -> Job:
        return self._job(self._row(job_id))

    def claim(self, worker_id: str, lease_seconds: float = 120.0) -> Job | None:
        """Take the next runnable job, first recovering any job whose lease expired."""
        now = self.clock()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for row in self.db.execute("SELECT id FROM jobs WHERE state IN (?,?) AND lease_expires_at < ?",
                                       (JobState.RUNNING.value, JobState.WAITING_FOR_PROVIDER.value, now)).fetchall():
                self._move(row["id"], JobState.QUEUED if self._row(row["id"])["state"] == "RUNNING" else JobState.RETRYING,
                           "lease expired; worker presumed dead", lease_owner=None, lease_expires_at=None)
                if self._row(row["id"])["state"] == JobState.RETRYING.value:
                    self._move(row["id"], JobState.QUEUED, "requeued after expired lease")
            row = self.db.execute("SELECT id FROM jobs WHERE state=? AND next_run_at<=? ORDER BY created_at LIMIT 1",
                                  (JobState.QUEUED.value, now)).fetchone()
            if row is None:
                self.db.execute("COMMIT")
                return None
            attempts = self._row(row["id"])["attempts"] + 1
            self._move(row["id"], JobState.RUNNING, f"claimed by {worker_id}", lease_owner=worker_id,
                       lease_expires_at=now + lease_seconds, attempts=attempts)
            self.db.execute("COMMIT")
            return self.get(row["id"])
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: float = 120.0) -> bool:
        cur = self.db.execute("UPDATE jobs SET lease_expires_at=?, updated_at=? WHERE id=? AND lease_owner=? AND state=?",
                              (self.clock() + lease_seconds, self.clock(), job_id, worker_id, JobState.RUNNING.value))
        return cur.rowcount == 1

    def _tx(self, fn) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            fn()
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def to_review(self, job_id: str) -> None:
        self._tx(lambda: self._move(job_id, JobState.QUALITY_REVIEW, "quality review"))

    def complete(self, job_id: str, result: dict) -> None:
        def go():
            if self._row(job_id)["state"] == JobState.RUNNING.value:
                self._move(job_id, JobState.QUALITY_REVIEW, "quality review")
            self._move(job_id, JobState.COMPLETED, "done", result=json.dumps(result), lease_owner=None,
                       lease_expires_at=None)
        self._tx(go)

    def fail(self, job_id: str, error: str, retryable: bool) -> Job:
        def go():
            row = self._row(job_id)
            if retryable and row["attempts"] < row["max_attempts"]:
                delay = min(self.max_backoff, self.base_backoff * 2 ** (row["attempts"] - 1))
                self._move(job_id, JobState.RETRYING, f"attempt {row['attempts']} failed: {error[:300]}",
                           last_error=error[:4000], lease_owner=None, lease_expires_at=None)
                self._move(job_id, JobState.QUEUED, f"retry in {delay:.0f}s", next_run_at=self.clock() + delay)
            else:
                why = "not retryable" if not retryable else f"gave up after {row['attempts']} attempts"
                self._move(job_id, JobState.FAILED, f"{why}: {error[:300]}", last_error=error[:4000],
                           lease_owner=None, lease_expires_at=None)
        self._tx(go)
        return self.get(job_id)

    def release(self, job_id: str, worker_id: str) -> None:
        """Graceful shutdown: hand a running job back to the queue without counting a failure."""
        def go():
            row = self._row(job_id)
            if row["state"] == JobState.RUNNING.value and row["lease_owner"] == worker_id:
                self._move(job_id, JobState.QUEUED, "released on shutdown", lease_owner=None,
                           lease_expires_at=None, attempts=max(0, row["attempts"] - 1))
        self._tx(go)

    def cancel(self, job_id: str, reason: str = "cancelled by owner") -> None:
        def go():
            if JobState(self._row(job_id)["state"]) not in TERMINAL_STATES:
                self._move(job_id, JobState.CANCELLED, reason, lease_owner=None, lease_expires_at=None)
        self._tx(go)

    def events(self, job_id: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT from_state, to_state, at, detail FROM job_events "
                                                 "WHERE job_id=? ORDER BY id", (job_id,))]

    def counts(self) -> dict:
        return {r["state"]: r["n"] for r in self.db.execute("SELECT state, COUNT(*) n FROM jobs GROUP BY state")}
