import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from auravox.queue import Blocked, Queue, Transient
from auravox.studio import Studio


def test_priority_dependencies_and_persistence(studio):
    q = Queue(studio)
    a = q.enqueue("t", {"v": "a"}, priority=10)
    b = q.enqueue("t", {"v": "b"}, priority=90, depends_on=[a])
    c = q.enqueue("t", {"v": "c"}, priority=50)
    order = []
    q.run({"t": lambda s, j: order.append(j["payload"]["v"]) or {"ok": True}}, workers=1)
    assert order == ["c", "a", "b"]                      # b waits for a despite its priority
    q2 = Queue(Studio(studio.home))                       # a new process sees the same state
    assert {q2.get(x)["status"] for x in (a, b, c)} == {"succeeded"}


def test_failed_dependency_blocks_children_and_transient_retries(studio):
    q = Queue(studio)
    calls = {"n": 0}

    def flaky(s, j):
        calls["n"] += 1
        if calls["n"] < 2:
            raise Transient("busy")
        return {}

    ok = q.enqueue("flaky", {}, max_attempts=3)
    bad = q.enqueue("bad", {}, max_attempts=1)
    child = q.enqueue("t", {}, depends_on=[bad])
    blk = q.enqueue("blk", {})
    studio.db.x("UPDATE jobs SET scheduled_at = 0")
    handlers = {"flaky": flaky, "bad": lambda s, j: 1 / 0, "t": lambda s, j: {}, "blk": lambda s, j: (_ for _ in ()).throw(Blocked("model missing"))}
    for _ in range(4):
        studio.db.x("UPDATE jobs SET scheduled_at = 0 WHERE status='queued'")
        q.run(handlers, workers=1)
    assert q.get(ok)["status"] == "succeeded" and q.get(ok)["attempts"] == 2
    assert q.get(bad)["status"] == "failed" and "ZeroDivisionError" in q.get(bad)["error"]
    assert q.get(child)["status"] == "blocked"
    assert q.get(blk)["status"] == "blocked" and q.get(blk)["attempts"] == 1      # never retried blindly


def test_cancel_pause_resume_retry(studio):
    q = Queue(studio)
    j = q.enqueue("t", {})
    q.pause(j)
    assert q.run({"t": lambda s, jj: {}}, workers=1)["succeeded"] == 0 and q.get(j)["status"] == "paused"
    q.resume(j)
    q.run({"t": lambda s, jj: {}}, workers=1)
    assert q.get(j)["status"] == "succeeded"
    k = q.enqueue("t", {})
    q.cancel(k)
    q.retry(k)
    assert q.get(k)["status"] == "queued"


def test_memory_guard_skips_jobs_that_do_not_fit(studio):
    q = Queue(studio)
    big = q.enqueue("t", {}, mem_mb=10_000)
    assert q.claim("w", max_mem_mb=4000) is None
    assert q.get(big)["status"] == "queued"


WORKER = """
import sys, time
from auravox.studio import Studio
from auravox.queue import Queue
s = Studio(sys.argv[1])
Queue(s).run({"slow": lambda st, j: time.sleep(30) or {}}, workers=1, until_idle=True)
"""


def test_crashed_worker_job_is_recovered_not_lost(studio, tmp_path):
    q = Queue(studio)
    jid = q.enqueue("slow", {}, max_attempts=3)
    script = tmp_path / "w.py"
    script.write_text(WORKER)
    env = dict(os.environ, AVX_LEASE="1.5", PYTHONPATH=str(Path(__file__).parents[1] / "src"))
    p = subprocess.Popen([sys.executable, str(script), str(studio.home)], env=env)
    for _ in range(100):
        if q.get(jid)["status"] == "running":
            break
        time.sleep(0.1)
    assert q.get(jid)["status"] == "running"
    os.kill(p.pid, signal.SIGKILL)                        # the worker dies mid-job
    p.wait()
    time.sleep(2.0)                                       # lease expires
    assert jid in q.recover()
    j = q.get(jid)
    assert j["status"] == "queued" and j["attempts"] == 1 and "recovered" in j["error"]
    q.run({"slow": lambda s, jj: {"resumed": True}}, workers=1)
    assert q.get(jid)["status"] == "succeeded" and q.get(jid)["attempts"] == 2
    assert any("recovered" in e["msg"] for e in studio.db.q("SELECT msg FROM events WHERE job_id=?", (jid,)))
