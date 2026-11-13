"""Persistent production queue (SQLite): priorities, dependencies, scheduling, leases, retries, cancel/pause/resume,
crash recovery and a memory guard.

States: queued -> running -> succeeded | failed | blocked | cancelled; paused (held); waiting for deps stays queued.
A worker leases a job for LEASE seconds and renews it while working; if a worker dies, the lease expires and the job
is re-queued (counting the attempt) instead of silently disappearing.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import traceback

LEASE = float(os.environ.get("AVX_LEASE", "120"))


class Transient(RuntimeError):
    """Worth retrying (timeouts, busy resources)."""


class Blocked(RuntimeError):
    """Needs a person or a missing capability (model not installed, language unsupported). Not retried."""


def mem_available_mb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable"):
                    return int(ln.split()[1]) / 1024
    except OSError:
        pass
    return 1e9


class Queue:
    def __init__(self, studio):
        self.s = studio
        self.db = studio.db

    # ---------------------------------------------------------------- create / control
    def enqueue(self, kind: str, payload: dict, title: str = "", priority: int = 50, depends_on: list | None = None,
                max_attempts: int = 3, mem_mb: int = 300, delay_s: float = 0, parent: str | None = None) -> str:
        jid = self.db.next_id("AVX-JOB")
        self.db.insert("jobs", {"id": jid, "kind": kind, "title": title or kind, "priority": priority, "status": "queued", "payload": payload,
                                "depends_on": depends_on or [], "attempts": 0, "max_attempts": max_attempts, "mem_mb": mem_mb,
                                "scheduled_at": time.time() + delay_s, "created": time.time(), "parent": parent})
        self.db.event(f"queued {kind} {title}", jid)
        return jid

    def cancel(self, jid: str) -> None:
        self.db.x("UPDATE jobs SET status='cancelled', finished=? WHERE id=? AND status IN ('queued','paused','blocked','failed')", (time.time(), jid))
        self.db.event("cancel requested", jid)

    def pause(self, jid: str) -> None:
        self.db.x("UPDATE jobs SET status='paused' WHERE id=? AND status='queued'", (jid,))

    def resume(self, jid: str) -> None:
        self.db.x("UPDATE jobs SET status='queued' WHERE id=? AND status='paused'", (jid,))

    def retry(self, jid: str) -> None:
        self.db.x("UPDATE jobs SET status='queued', attempts=0, error=NULL, scheduled_at=? WHERE id=? AND status IN ('failed','blocked','cancelled')",
                  (time.time(), jid))
        self.db.event("manual retry", jid)

    def get(self, jid: str) -> dict:
        return self.db.one("SELECT * FROM jobs WHERE id=?", (jid,))

    # ---------------------------------------------------------------- recovery
    def recover(self) -> list[str]:
        """Jobs whose worker died (lease expired) go back to the queue, or fail if out of attempts."""
        now = time.time()
        back = []
        for j in self.db.q("SELECT * FROM jobs WHERE status='running' AND (lease_until IS NULL OR lease_until < ?)", (now,)):
            if j["attempts"] >= j["max_attempts"]:
                self.db.update("jobs", "id", j["id"], status="failed", finished=now, error=(j["error"] or "") + " | worker lost, out of attempts")
            else:
                self.db.update("jobs", "id", j["id"], status="queued", worker=None, lease_until=None, error="recovered after worker loss")
                back.append(j["id"])
            self.db.event("recovered from expired lease", j["id"], "warn")
        return back

    # ---------------------------------------------------------------- claim
    def _deps_state(self, deps: list[str]) -> str:
        if not deps:
            return "ok"
        st = {r["status"] for r in self.db.q(f"SELECT status FROM jobs WHERE id IN ({','.join('?' * len(deps))})", deps)}
        if st & {"failed", "blocked", "cancelled"}:
            return "broken"
        return "ok" if st == {"succeeded"} else "wait"

    def claim(self, worker: str, max_mem_mb: float | None = None) -> dict | None:
        free = mem_available_mb() if max_mem_mb is None else max_mem_mb
        with self.db._lock:
            for j in self.db.q("SELECT * FROM jobs WHERE status='queued' AND scheduled_at <= ? ORDER BY priority DESC, created", (time.time(),)):
                d = self._deps_state(j["depends_on"])
                if d == "broken":
                    self.db.update("jobs", "id", j["id"], status="blocked", error="a dependency failed, was blocked or cancelled", finished=time.time())
                    continue
                if d == "wait":
                    continue
                if j["mem_mb"] > free - 200:
                    continue                               # not enough memory now; another job may fit
                cur = self.db.x("UPDATE jobs SET status='running', worker=?, lease_until=?, attempts=attempts+1, started=? WHERE id=? AND status='queued'",
                                (worker, time.time() + LEASE, time.time(), j["id"]))
                if cur.rowcount == 1:
                    return self.get(j["id"])
        return None

    def heartbeat(self, jid: str) -> None:
        self.db.x("UPDATE jobs SET lease_until=? WHERE id=? AND status='running'", (time.time() + LEASE, jid))

    def finish(self, jid: str, result: dict) -> None:
        self.db.update("jobs", "id", jid, status="succeeded", result=result, finished=time.time(), lease_until=None, error=None)
        self.db.event("succeeded", jid)

    def fail(self, jid: str, err: BaseException) -> None:
        j = self.get(jid)
        msg = f"{type(err).__name__}: {err}"
        if isinstance(err, Blocked):
            self.db.update("jobs", "id", jid, status="blocked", error=msg, finished=time.time(), lease_until=None)
        elif j["attempts"] < j["max_attempts"]:
            back = min(60, 2 ** j["attempts"])
            self.db.update("jobs", "id", jid, status="queued", error=msg, scheduled_at=time.time() + back, lease_until=None)
        else:
            self.db.update("jobs", "id", jid, status="failed", error=msg, finished=time.time(), lease_until=None)
        self.db.event(msg, jid, "error")

    # ---------------------------------------------------------------- workers
    def run(self, handlers: dict, workers: int = 2, until_idle: bool = True, max_seconds: float | None = None, log=print) -> dict:
        self.recover()
        name = f"{socket.gethostname()}:{os.getpid()}"
        t0 = time.time()
        done = {"succeeded": 0, "failed": 0}
        stop = threading.Event()

        def loop(i):
            idle = 0
            while not stop.is_set():
                if max_seconds and time.time() - t0 > max_seconds:
                    return
                j = self.claim(f"{name}/w{i}")
                if not j:
                    pending = self.db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running')")["n"]
                    if until_idle and pending == 0:
                        return
                    idle += 1
                    time.sleep(0.2 if idle < 50 else 1.0)
                    continue
                idle = 0
                beat = threading.Event()

                def keep(jid=j["id"]):
                    while not beat.wait(LEASE / 3):
                        self.heartbeat(jid)

                hb = threading.Thread(target=keep, daemon=True)
                hb.start()
                try:
                    h = handlers.get(j["kind"])
                    if not h:
                        raise Blocked(f"no handler for job kind {j['kind']}")
                    log(f"[w{i}] {j['id']} {j['kind']} {j['title']} (attempt {j['attempts']})")
                    res = h(self.s, j)
                    self.finish(j["id"], res or {})
                    done["succeeded"] += 1
                except Exception as e:  # noqa: BLE001 - classified and recorded, never swallowed
                    self.db.update("jobs", "id", j["id"], result={"traceback": traceback.format_exc()[-2000:]})
                    self.fail(j["id"], e)
                    done["failed"] += 1
                    log(f"[w{i}] {j['id']} {type(e).__name__}: {e}")
                finally:
                    beat.set()

        ts = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(workers)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return done | {"seconds": round(time.time() - t0, 1)}

    def summary(self) -> dict:
        return {r["status"]: r["n"] for r in self.db.q("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
