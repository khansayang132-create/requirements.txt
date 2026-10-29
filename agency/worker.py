"""Long-running worker: resumes approved missions and runs a playbook on a schedule.

    python -m agency worker --every 3600 --playbook health      # Ctrl+C / SIGTERM stops it cleanly

Each loop: record a heartbeat, resume every mission that is READY (or was left RUNNING by a dead worker, via
lease recovery), and when the schedule is due, plan and run the scheduled playbook. It never approves anything
and never resumes a mission waiting for approval. One mission runs at a time; the loop sleeps in 1-second
steps so a stop signal is honoured quickly. Supervision (restart on crash, start at boot) is the job of the
host: a systemd unit, runit, or the scheduled GitHub workflow `.github/workflows/agency-nightly.yml`.
"""
from __future__ import annotations

import signal
import threading
import time

from . import orchestrator as orch
from .store import InvalidTransition, Store
from .tools import Toolbox


class Worker:
    def __init__(self, store: Store, toolbox: Toolbox, playbook: str | None, every: float, concurrency: int = 4,
                 clock=time.time, idle: float = 120.0):
        self.store, self.toolbox, self.playbook, self.every, self.idle = store, toolbox, playbook, every, idle
        self.orch = orch.Orchestrator(store, toolbox, concurrency)
        self.clock = clock
        self.stop = threading.Event()
        self.last_scheduled = 0.0

    def resumable(self) -> list[str]:
        """Approved READY/RUNNING missions that nobody else is working on: no task holds a live lease and no
        task changed in the last `idle` seconds (a `run` in another process is busy with it)."""
        now = self.store.clock()
        rows = self.store.db.execute(
            "SELECT id FROM missions m WHERE state IN ('READY','RUNNING') AND (requires_approval=0 OR approved_by "
            "IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.mission_id=m.id AND (t.updated_at > ? OR "
            "(t.state='RUNNING' AND t.lease_expires_at >= ?))) ORDER BY created_at", (now - self.idle, now)).fetchall()
        return [r["id"] for r in rows]

    def tick(self) -> list[tuple[str, str]]:
        """One loop iteration. Returns (mission id, final state) for every mission it ran."""
        self.store.heartbeat(self.orch.worker, f"playbook={self.playbook} every={self.every}")
        ran: list[tuple[str, str]] = []
        for mid in self.resumable():
            if self.stop.is_set():
                return ran
            try:
                ran.append((mid, self.orch.run(mid)))
            except InvalidTransition as e:  # another process claimed it first; theirs to finish
                ran.append((mid, f"skipped: {e}"))
        if self.playbook and self.clock() - self.last_scheduled >= self.every and not self.stop.is_set():
            self.last_scheduled = self.clock()
            mid = orch.plan(self.store, self.toolbox, self.playbook)
            ran.append((mid, self.orch.run(mid)))
        return ran

    def forever(self, poll: float = 30.0, log=print) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: self.stop.set())
        log(f"agency worker {self.orch.worker}: playbook={self.playbook} every={self.every:.0f}s")
        while not self.stop.is_set():
            for mid, state in self.tick():
                log(f"{mid}: {state}")
            for _ in range(int(poll)):
                if self.stop.is_set():
                    break
                time.sleep(1)
        log("agency worker stopped")

