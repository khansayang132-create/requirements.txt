"""Persistent missions, tasks, state history and tool-call audit log on SQLite.

A mission is one run of a playbook; its tasks are fixed when it is planned (agents cannot create tasks, so
there is no delegation to loop on). Every state change goes through `_move`, which checks it against
TRANSITIONS and writes an `events` row. Tool calls are written to `tool_calls` with redacted output, and
verification reads the evidence back from that table rather than trusting the runner's own report.

Leases: a RUNNING task records its owner and a lease expiry. After a crash, `recover()` moves tasks whose
lease expired back to READY, so a restarted orchestrator picks them up again.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from enum import StrEnum
from pathlib import Path


class State(StrEnum):
    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PLANNED = "PLANNED"
    READY = "READY"
    RUNNING = "RUNNING"
    REVIEWING = "REVIEWING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"


S = State
TRANSITIONS: dict[State, set[State]] = {
    S.CREATED: {S.ANALYZING, S.CANCELLED},
    S.ANALYZING: {S.PLANNED, S.BLOCKED, S.FAILED, S.CANCELLED},
    S.PLANNED: {S.READY, S.NEEDS_APPROVAL, S.CANCELLED},
    S.NEEDS_APPROVAL: {S.READY, S.CANCELLED},
    S.READY: {S.RUNNING, S.BLOCKED, S.CANCELLED},
    S.RUNNING: {S.REVIEWING, S.READY, S.FAILED, S.BLOCKED, S.NEEDS_APPROVAL, S.VERIFYING, S.CANCELLED},
    S.REVIEWING: {S.VERIFYING, S.FAILED},
    S.VERIFYING: {S.COMPLETED, S.FAILED},
    S.BLOCKED: {S.READY, S.CANCELLED},
    S.FAILED: {S.READY},  # only by an explicit human retry
    S.COMPLETED: set(),
    S.CANCELLED: set(),
}
FINAL = {S.COMPLETED, S.FAILED, S.BLOCKED, S.CANCELLED}

SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
  id TEXT PRIMARY KEY, playbook TEXT NOT NULL, title TEXT NOT NULL, state TEXT NOT NULL,
  call_budget INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, step TEXT NOT NULL, title TEXT NOT NULL,
  role TEXT NOT NULL, verifier TEXT NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL,
  handoff TEXT NOT NULL, depends_on TEXT NOT NULL, state TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 2,
  approved_by TEXT, lease_owner TEXT, lease_expires_at REAL,
  status TEXT, summary TEXT, verification TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  UNIQUE (mission_id, step));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
  from_state TEXT, to_state TEXT NOT NULL, at REAL NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS tool_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, mission_id TEXT NOT NULL, role TEXT NOT NULL,
  tool TEXT NOT NULL, args TEXT NOT NULL, attempt INTEGER NOT NULL, started_at REAL NOT NULL,
  finished_at REAL NOT NULL, status TEXT NOT NULL, exit_code INTEGER, summary TEXT NOT NULL,
  output TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_entity ON events(entity_id, id);
CREATE INDEX IF NOT EXISTS tasks_mission ON tasks(mission_id, state);
"""


class InvalidTransition(RuntimeError):
    pass


class Store:
    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------- transitions
    def _move(self, entity: str, entity_id: str, to: State, detail: str = "", **fields) -> None:
        table = "missions" if entity == "mission" else "tasks"
        row = self.db.execute(f"SELECT state FROM {table} WHERE id=?", (entity_id,)).fetchone()
        if row is None:
            raise KeyError(f"no {entity} {entity_id}")
        frm = State(row["state"])
        if to not in TRANSITIONS[frm]:
            raise InvalidTransition(f"{entity} {entity_id}: {frm.value} -> {to.value}")
        now = self.clock()
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.db.execute(f"UPDATE {table} SET state=?, updated_at=?{', ' + sets if sets else ''} "
                                  "WHERE id=? AND state=?", (to.value, now, *fields.values(), entity_id, frm.value))
            if cur.rowcount != 1:
                raise InvalidTransition(f"{entity} {entity_id} changed state concurrently")
            self.db.execute("INSERT INTO events (entity, entity_id, from_state, to_state, at, detail) "
                            "VALUES (?,?,?,?,?,?)", (entity, entity_id, frm.value, to.value, now, detail))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def move_mission(self, mission_id: str, to: State, detail: str = "") -> None:
        self._move("mission", mission_id, to, detail)

    def move_task(self, task_id: str, to: State, detail: str = "", **fields) -> None:
        self._move("task", task_id, to, detail, **fields)

    # ----------------------------------------------------------------- create
    def create_mission(self, playbook: str, title: str, call_budget: int) -> str:
        mid = "m-" + uuid.uuid4().hex[:10]
        now = self.clock()
        self.db.execute("INSERT INTO missions VALUES (?,?,?,?,?,?,?)",
                        (mid, playbook, title, S.CREATED.value, call_budget, now, now))
        self.db.execute("INSERT INTO events (entity, entity_id, from_state, to_state, at, detail) "
                        "VALUES ('mission', ?, NULL, 'CREATED', ?, ?)", (mid, now, f"playbook {playbook}"))
        return mid

    def add_task(self, mission_id: str, step, verifier: str, max_attempts: int) -> str:
        tid = f"{mission_id}.{step.id}"
        now = self.clock()
        self.db.execute(
            "INSERT INTO tasks (id, mission_id, step, title, role, verifier, tool, args, handoff, depends_on, state, "
            "max_attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, mission_id, step.id, step.title, step.role, verifier, step.tool, json.dumps(step.args),
             json.dumps(step.handoff), json.dumps(list(step.after)), S.PLANNED.value, max_attempts, now, now))
        self.db.execute("INSERT INTO events (entity, entity_id, from_state, to_state, at, detail) "
                        "VALUES ('task', ?, NULL, 'PLANNED', ?, ?)", (tid, now, f"{step.role} -> {step.tool}"))
        return tid

    def record_call(self, task: sqlite3.Row, attempt: int, started: float, args: dict, result) -> int:
        cur = self.db.execute(
            "INSERT INTO tool_calls (task_id, mission_id, role, tool, args, attempt, started_at, finished_at, status, "
            "exit_code, summary, output, evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task["id"], task["mission_id"], task["role"], task["tool"], json.dumps(args), attempt, started,
             self.clock(), result.status, result.exit_code, result.summary, result.output,
             json.dumps(result.evidence, default=str)))
        return int(cur.lastrowid or 0)

    # ------------------------------------------------------------------ reads
    def mission(self, mission_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        if row is None:
            raise KeyError(f"no mission {mission_id}")
        return row

    def missions(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM missions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()

    def tasks(self, mission_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM tasks WHERE mission_id=? ORDER BY created_at, rowid",
                               (mission_id,)).fetchall()

    def task(self, task_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"no task {task_id}")
        return row

    def events(self, entity_id_prefix: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM events WHERE entity_id=? OR entity_id LIKE ? ORDER BY id",
                               (entity_id_prefix, entity_id_prefix + ".%")).fetchall()

    def calls(self, mission_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM tool_calls WHERE mission_id=? ORDER BY id", (mission_id,)).fetchall()

    def last_call(self, task_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM tool_calls WHERE task_id=? ORDER BY id DESC LIMIT 1",
                               (task_id,)).fetchone()

    def call_count(self, mission_id: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM tool_calls WHERE mission_id=?", (mission_id,)).fetchone()[0]

    # --------------------------------------------------------------- recovery
    def recover(self, mission_id: str) -> list[str]:
        """Move RUNNING tasks whose lease expired back to READY. Returns their ids."""
        recovered = []
        for row in self.db.execute("SELECT id FROM tasks WHERE mission_id=? AND state='RUNNING' AND "
                                   "(lease_expires_at IS NULL OR lease_expires_at < ?)",
                                   (mission_id, self.clock())).fetchall():
            self.move_task(row["id"], S.READY, "lease expired (orchestrator restarted); re-queued",
                           lease_owner=None, lease_expires_at=None)
            recovered.append(row["id"])
        return recovered
