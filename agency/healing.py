"""Self-healing engine: health monitor, task watchdog, error classifier, retry manager, recovery log, diagnostics.

One `heal()` pass (the worker runs it every loop; `python -m agency heal` runs it by hand):

1. Watchdog: RUNNING tasks whose lease expired (their runner died) go back to READY via `Store.recover`, so a
   live worker resumes them. A worker whose heartbeat is older than STALE_WORKER is reported as stalled.
2. Classifier: every BLOCKED or FAILED task gets a category from its recorded status and summary:
   transient, missing_dependency, credential, approval, budget, dependency, check_failed, unknown.
3. Retry manager, with a bounded, exponentially backed-off number of attempts per task (MAX_HEALS):
   - transient: a FAILED task that failed by ERROR (timeout, crash) and a BLOCKED one with a transient reason are
     put back to READY after base * 2**n seconds. A FAIL verdict (a real check that found a problem) is never retried.
   - missing_dependency: retried with a longer backoff, so installing the program heals the task without a human.
   - credential, approval, check_failed, unknown, budget: never retried automatically; escalated once (recorded with
     what a person must do). External authorization is never bypassed.
   - dependency: not handled on its own; when the upstream task is retried, its BLOCKED dependants come back too.
4. Recurring failures: the same playbook step not passing in RECURRING missions within a week is escalated once.

Every action, including "escalated" and "gave up", is a row in `recoveries`; nothing is silently dropped.
"""
from __future__ import annotations

import json
import re

from .store import FINAL, State, Store

MAX_HEALS = 3
BACKOFF = {"transient": 60.0, "missing_dependency": 600.0}
STALE_WORKER = 900.0
RECURRING = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS recoveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, mission_id TEXT, task_id TEXT, category TEXT NOT NULL,
  action TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, next_at REAL, detail TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS recoveries_task ON recoveries(task_id, id);
"""

RULES: list[tuple[str, re.Pattern]] = [
    ("approval", re.compile(r"requires human approval|needs human approval|waiting for human", re.I)),
    ("credential", re.compile(r"no credential|api[_ ]?key|not logged in|unauthori[sz]ed|forbidden|HTTP 40[13]|"
                              r"not configured: set", re.I)),
    ("budget", re.compile(r"budget exhausted", re.I)),
    ("dependency", re.compile(r"dependency did not pass", re.I)),
    ("missing_dependency", re.compile(r"is not installed|not installed|no .{0,30}model is installed|no module named|missing|"
                                      r"command not found|"
                                      r"no such file", re.I)),
    ("transient", re.compile(r"timed out|timeout|temporar|connection (reset|refused)|unreachable|busy|locked|"
                             r"HTTP 5\d\d|lease expired|errored|gave up after", re.I)),
]
ESCALATE = {
    "credential": "a person must add the credential to .env (or log in); the system will not invent or bypass it",
    "approval": "a person must approve the task (`python -m agency approve TASK_ID`)",
    "check_failed": "a real check found a problem: fix the code or content, then `python -m agency retry MISSION`",
    "budget": "the mission's tool-call budget ran out; re-plan it with a larger budget if that is intended",
    "unknown": "unclassified failure: read the task's tool call output in `python -m agency show MISSION`",
}


def classify(status: str | None, summary: str | None) -> str:
    """Category of a non-passing task, from its recorded verdict and summary. A FAIL is a real finding."""
    text = summary or ""
    for category, pattern in RULES:
        if pattern.search(text):
            if category == "transient" and status == "FAIL":
                break
            return category
    if status == "FAIL":
        return "check_failed"
    if status == "ERROR":
        return "transient"
    return "unknown"


class Healer:
    def __init__(self, store: Store, clock=None):
        self.store, self.clock = store, clock or store.clock
        store.db.executescript(SCHEMA)

    # ------------------------------------------------------------------ log
    def _log(self, category: str, action: str, detail: str, task=None, attempt: int = 0, next_at: float | None = None):
        self.store.db.execute(
            "INSERT INTO recoveries (at, mission_id, task_id, category, action, attempt, next_at, detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.clock(), task["mission_id"] if task is not None else None, task["id"] if task is not None else None,
             category, action, attempt, next_at, detail[:1000]))

    def history(self, task_id: str) -> list:
        return self.store.db.execute("SELECT * FROM recoveries WHERE task_id=? ORDER BY id", (task_id,)).fetchall()

    def recent(self, limit: int = 50) -> list:
        return self.store.db.execute("SELECT * FROM recoveries ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ------------------------------------------------------------------ monitor
    def stalled_workers(self) -> list[dict]:
        now = self.clock()
        return [{"worker": h["worker"], "age_s": round(now - h["at"])} for h in self.store.heartbeats()
                if now - h["at"] > STALE_WORKER]

    def watchdog(self) -> list[str]:
        """Re-queue tasks whose runner died (lease expired)."""
        recovered = []
        for m in self.store.db.execute("SELECT DISTINCT mission_id FROM tasks WHERE state='RUNNING' AND "
                                       "(lease_expires_at IS NULL OR lease_expires_at < ?)", (self.clock(),)).fetchall():
            for tid in self.store.recover(m["mission_id"]):
                task = self.store.task(tid)
                self._log("transient", "requeued", "lease expired: the runner stopped; task back to READY", task)
                recovered.append(tid)
        return recovered

    # ------------------------------------------------------------------ retry manager
    def _attempts(self, task_id: str) -> tuple[int, float | None]:
        rows = [r for r in self.history(task_id) if r["action"] in ("retry", "scheduled")]
        retries = [r for r in rows if r["action"] == "retry"]
        pending = rows[-1]["next_at"] if rows and rows[-1]["action"] == "scheduled" else None
        return len(retries), pending

    def _escalated(self, task_id: str, category: str) -> bool:
        return any(r["action"] == "escalated" and r["category"] == category for r in self.history(task_id))

    def _requeue(self, task, detail: str) -> None:
        s = self.store
        s.move_task(task["id"], State.READY, detail, max_attempts=task["attempts"] + 1)
        steps = {t["step"]: t for t in s.tasks(task["mission_id"])}
        # dependants blocked only because this task did not pass come back with it
        for t in steps.values():
            if t["state"] == State.BLOCKED.value and t["status"] is None and task["step"] in json.loads(t["depends_on"]):
                s.move_task(t["id"], State.READY, f"upstream {task['step']} is being retried by self-healing")
        m = s.mission(task["mission_id"])
        if m["state"] in (State.FAILED.value, State.BLOCKED.value):
            s.move_mission(m["id"], State.READY, f"self-healing retry of {task['step']}")

    def handle(self, task) -> str:
        category = classify(task["status"], task["summary"])
        if category == "dependency" or task["status"] is None:  # never ran: blocked by its upstream
            return "waiting on upstream"
        if task["state"] == State.FAILED.value and task["status"] != "ERROR":
            category = "check_failed" if category in ("transient", "missing_dependency", "unknown") else category
        if category in ESCALATE:
            if not self._escalated(task["id"], category):
                self._log(category, "escalated", f"{ESCALATE[category]} (task said: {task['summary']})", task)
            return "escalated"
        done, pending = self._attempts(task["id"])
        if done >= MAX_HEALS:
            if not any(r["action"] == "gave_up" for r in self.history(task["id"])):
                self._log(category, "gave_up", f"{done} self-healing retries used; needs a person: {task['summary']}", task, done)
            return "gave up"
        now = self.clock()
        if pending is None:
            nxt = now + BACKOFF[category] * 2 ** done
            self._log(category, "scheduled", f"retry {done + 1}/{MAX_HEALS} at +{nxt - now:.0f}s: {task['summary']}",
                      task, done + 1, nxt)
            return "scheduled"
        if now < pending:
            return "backing off"
        self._requeue(task, f"self-healing retry {done + 1}/{MAX_HEALS} ({category})")
        self._log(category, "retry", f"task back to READY ({category}): {task['summary']}", task, done + 1)
        return "retried"

    # ------------------------------------------------------------------ recurring failures
    def recurring(self) -> list[dict]:
        since = self.clock() - 7 * 86400
        rows = self.store.db.execute(
            "SELECT m.playbook, t.step, COUNT(DISTINCT t.mission_id) n, MAX(t.summary) summary FROM tasks t "
            "JOIN missions m ON m.id=t.mission_id WHERE t.state IN ('FAILED','BLOCKED') AND t.updated_at > ? "
            "GROUP BY m.playbook, t.step HAVING n >= ?", (since, RECURRING)).fetchall()
        out = []
        for r in rows:
            key = f"{r['playbook']}.{r['step']}"
            if not self.store.db.execute("SELECT 1 FROM recoveries WHERE category='recurring' AND detail LIKE ?",
                                         (key + ":%",)).fetchone():
                self._log("recurring", "escalated", f"{key}: did not pass in {r['n']} missions this week; last: {r['summary']}")
            out.append({"step": key, "missions": r["n"]})
        return out

    # ------------------------------------------------------------------ one pass
    def heal(self) -> dict:
        report = {"requeued": self.watchdog(), "stalled_workers": self.stalled_workers(), "actions": {}}
        for t in self.store.db.execute("SELECT * FROM tasks WHERE state IN ('FAILED','BLOCKED')").fetchall():
            m = self.store.mission(t["mission_id"])
            if State(m["state"]) not in FINAL and m["state"] != State.READY.value:
                continue  # a runner is still working on this mission; let it finish first
            report["actions"][t["id"]] = self.handle(t)
        report["recurring"] = self.recurring()
        return report

    def diagnostics(self) -> dict:
        db = self.store.db
        by_state = {r["state"]: r["n"] for r in db.execute("SELECT state, COUNT(*) n FROM tasks GROUP BY state")}
        cats: dict[str, int] = {}
        for t in db.execute("SELECT status, summary FROM tasks WHERE state IN ('FAILED','BLOCKED')").fetchall():
            c = classify(t["status"], t["summary"])
            cats[c] = cats.get(c, 0) + 1
        return {"tasks_by_state": by_state, "non_passing_by_category": cats, "stalled_workers": self.stalled_workers(),
                "recoveries": len(db.execute("SELECT id FROM recoveries").fetchall())}
