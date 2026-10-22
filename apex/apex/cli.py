"""Command line.

  python -m apex.cli run      --spec spec.json --project out/ [--script script.json]
  python -m apex.cli enqueue  --spec spec.json --project out/ [--script script.json] --db jobs.db
  python -m apex.cli worker   --db jobs.db            # runs until SIGTERM/SIGINT
  python -m apex.cli status   --db jobs.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import socket
import threading
import time
from pathlib import Path

from .jobs import JobQueue
from .models import ProductionSpec
from .pipeline import PipelineError, RenderSettings, run_production
from .script_engine import ProviderUnavailable


def _spec(path: str) -> ProductionSpec:
    return ProductionSpec.model_validate_json(Path(path).read_text(encoding="utf-8"))


def cmd_run(a) -> None:
    m = run_production(_spec(a.spec), Path(a.project), Path(a.script) if a.script else None,
                       RenderSettings(fps=a.fps, samples=a.samples))
    print(json.dumps({"final": m["outputs"]["final_video"], "qa": m["qa"]}, indent=2))


def cmd_enqueue(a) -> None:
    payload = {"spec": json.loads(Path(a.spec).read_text(encoding="utf-8")), "project": str(Path(a.project).resolve()),
               "script": str(Path(a.script).resolve()) if a.script else None, "fps": a.fps, "samples": a.samples}
    key = a.key or hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    job = JobQueue(Path(a.db)).enqueue(key, "produce_video", payload)
    print(json.dumps({"job_id": job.id, "state": job.state.value, "idempotency_key": key}))


def cmd_worker(a) -> None:
    q = JobQueue(Path(a.db))
    worker_id = f"{socket.gethostname()}-{int(time.time())}"
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    print(f"worker {worker_id} started")
    while not stop.is_set():
        job = q.claim(worker_id, lease_seconds=a.lease)
        if job is None:
            stop.wait(a.poll)
            continue
        print(f"job {job.id} attempt {job.attempts}")
        beat_stop = threading.Event()

        def beat():
            # Separate connection: SQLite connections must not be shared across threads.
            hq = JobQueue(Path(a.db))
            while not beat_stop.wait(a.lease / 3):
                hq.heartbeat(job.id, worker_id, a.lease)

        t = threading.Thread(target=beat, daemon=True)
        t.start()
        p = job.payload
        try:
            m = run_production(ProductionSpec.model_validate(p["spec"]), Path(p["project"]),
                               Path(p["script"]) if p.get("script") else None,
                               RenderSettings(fps=p.get("fps", 24), samples=p.get("samples", 8)))
            q.complete(job.id, {"final": m["outputs"]["final_video"], "qa": m["qa"]})
            print(f"job {job.id} COMPLETED")
        except ProviderUnavailable as e:
            q.fail(job.id, f"provider unavailable: {e}", retryable=False)
        except PipelineError as e:
            print(f"job {job.id} error: {e}")
            q.fail(job.id, str(e), retryable=e.retryable)
        except Exception as e:  # noqa: BLE001  unexpected errors are retried, then dead-lettered
            print(f"job {job.id} unexpected error: {e!r}")
            q.fail(job.id, repr(e), retryable=True)
        finally:
            beat_stop.set()
            t.join(timeout=5)
    print("worker stopped")


def cmd_status(a) -> None:
    q = JobQueue(Path(a.db))
    rows = q.db.execute("SELECT id, state, attempts, last_error, updated_at FROM jobs ORDER BY created_at DESC LIMIT 20")
    print(json.dumps({"counts": q.counts(), "recent": [dict(r) for r in rows]}, indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(prog="apex")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "enqueue"):
        p = sub.add_parser(name)
        p.add_argument("--spec", required=True)
        p.add_argument("--project", required=True)
        p.add_argument("--script")
        p.add_argument("--fps", type=int, default=24)
        p.add_argument("--samples", type=int, default=8)
        if name == "enqueue":
            p.add_argument("--db", required=True)
            p.add_argument("--key")
    w = sub.add_parser("worker")
    w.add_argument("--db", required=True)
    w.add_argument("--lease", type=float, default=300)
    w.add_argument("--poll", type=float, default=5)
    s = sub.add_parser("status")
    s.add_argument("--db", required=True)
    a = ap.parse_args()
    {"run": cmd_run, "enqueue": cmd_enqueue, "worker": cmd_worker, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    main()
