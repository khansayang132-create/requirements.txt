"""Command line.

  python -m apex.cli run      --spec spec.json --project out/ [--script script.json]
  python -m apex.cli enqueue  --spec spec.json --project out/ [--script script.json] --db jobs.db
  python -m apex.cli worker   --db jobs.db            # runs until SIGTERM/SIGINT
  python -m apex.cli status   --db jobs.db
  python -m apex.cli plan     --plan plan.json --db jobs.db    # enqueue what the autopilot policy allows
  python -m apex.cli stop     --db jobs.db                     # emergency stop: workers take no new jobs
  python -m apex.cli resume   --db jobs.db
  python -m apex.cli policy   --db jobs.db [--max-per-day N] [--require-approval yes|no]
  python -m apex.cli dashboard --db jobs.db [--port 8787]      # read-only control center
  python -m apex.cli ideas    --plan plan.json [--db jobs.db] [--count 5]   # LLM ideas, added unapproved
  python -m apex.cli approve  --plan plan.json --id ID [--id ID ...]
  python -m apex.cli backup   --db jobs.db [--out backups/] [--plan plan.json] [--keep 14]
  python -m apex.cli verify-backup --dir backups/apex-backup-...
  python -m apex.cli review   --project out/my-video          # vision-model creative review (advisory)

The autopilot policy lives in autopilot.json next to the database unless --policy is given.
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

from .autopilot import load_policy, run_plan, save_policy
from .jobs import JobQueue
from .models import ProductionSpec
from .pipeline import PipelineError, RenderSettings, run_production
from .script_engine import ProviderUnavailable


def _policy_path(a) -> Path:
    return Path(a.policy) if getattr(a, "policy", None) else Path(a.db).with_name("autopilot.json")


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
    paused_reported = False
    while not stop.is_set():
        if load_policy(_policy_path(a)).paused:
            if not paused_reported:
                print("autopilot paused (emergency stop): not taking new jobs")
                paused_reported = True
            stop.wait(a.poll)
            continue
        paused_reported = False
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


def cmd_plan(a) -> None:
    plan_file = Path(a.plan)
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    decisions = run_plan(plan, JobQueue(Path(a.db)), load_policy(_policy_path(a)), plan_file.parent)
    print(json.dumps(decisions, indent=2, ensure_ascii=False))


def _set_paused(a, paused: bool) -> None:
    policy = load_policy(_policy_path(a))
    policy.paused = paused
    save_policy(policy, _policy_path(a))
    print(json.dumps({"paused": paused, "policy": str(_policy_path(a))}))


def cmd_policy(a) -> None:
    policy = load_policy(_policy_path(a))
    if a.max_per_day is not None:
        policy.max_jobs_per_day = a.max_per_day
    if a.require_approval is not None:
        policy.require_approval = a.require_approval == "yes"
    if a.allow is not None:
        policy.allowed_topics = [t.strip() for t in a.allow.split(",") if t.strip()]
    if a.prohibit is not None:
        policy.prohibited_topics = [t.strip() for t in a.prohibit.split(",") if t.strip()]
    save_policy(policy, _policy_path(a))
    print(policy.model_dump_json(indent=2))


def cmd_ideas(a) -> None:
    from .ideas import generate_ideas
    from .script_engine import provider_from_env
    policy = load_policy(_policy_path(a) if a.db or a.policy else Path(a.plan).with_name("autopilot.json"))
    out = generate_ideas(provider_from_env(), Path(a.plan), policy, a.count, JobQueue(Path(a.db)) if a.db else None)
    print(json.dumps({"added": [{"id": e["id"], "angle": e["angle"], "topic": e["spec"]["topic"], "hook": e["hook"]}
                                for e in out["added"]], "rejected": out["rejected"], "plan": out["plan"]},
                     indent=2, ensure_ascii=False))


def cmd_approve(a) -> None:
    plan_file = Path(a.plan)
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    ids = set(a.id)
    found = [e["id"] for e in plan if e.get("id") in ids]
    for e in plan:
        if e.get("id") in ids:
            e["approved"] = True
    tmp = plan_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(plan_file)
    print(json.dumps({"approved": found, "not_found": sorted(ids - set(found))}))
    if ids - set(found):
        raise SystemExit(1)


def cmd_backup(a) -> None:
    from .backup import backup
    out = Path(a.out) if a.out else Path(a.db).with_name("backups")
    dest = backup(Path(a.db), out, [_policy_path(a)] + [Path(p) for p in a.plan or []], a.keep)
    print(json.dumps({"backup": str(dest)}))


def cmd_verify_backup(a) -> None:
    from .backup import verify
    problems = verify(Path(a.dir))
    print(json.dumps({"ok": not problems, "problems": problems}))
    if problems:
        raise SystemExit(1)


def cmd_review(a) -> None:
    from .vision import review_project
    review = review_project(Path(a.project))
    print(json.dumps(review, indent=2, ensure_ascii=False))


def cmd_dashboard(a) -> None:
    from .dashboard import serve
    srv = serve(Path(a.db), _policy_path(a), a.host, a.port)
    print(f"dashboard on http://{a.host}:{srv.server_port}  (read-only; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


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
    w.add_argument("--policy")
    s = sub.add_parser("status")
    s.add_argument("--db", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--plan", required=True)
    pl.add_argument("--db", required=True)
    pl.add_argument("--policy")
    for name in ("stop", "resume"):
        x = sub.add_parser(name)
        x.add_argument("--db", required=True)
        x.add_argument("--policy")
    po = sub.add_parser("policy")
    po.add_argument("--db", required=True)
    po.add_argument("--policy")
    po.add_argument("--max-per-day", type=int)
    po.add_argument("--require-approval", choices=["yes", "no"])
    po.add_argument("--allow", help="comma-separated allowed topic keywords ('' clears)")
    po.add_argument("--prohibit", help="comma-separated prohibited topic keywords ('' clears)")
    d = sub.add_parser("dashboard")
    d.add_argument("--db", required=True)
    d.add_argument("--policy")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8787)
    i = sub.add_parser("ideas")
    i.add_argument("--plan", required=True)
    i.add_argument("--db")
    i.add_argument("--policy")
    i.add_argument("--count", type=int, default=5)
    ap_ = sub.add_parser("approve")
    ap_.add_argument("--plan", required=True)
    ap_.add_argument("--id", action="append", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--db", required=True)
    b.add_argument("--policy")
    b.add_argument("--out")
    b.add_argument("--plan", action="append")
    b.add_argument("--keep", type=int, default=14)
    vb = sub.add_parser("verify-backup")
    vb.add_argument("--dir", required=True)
    rv = sub.add_parser("review")
    rv.add_argument("--project", required=True)
    a = ap.parse_args()
    {"run": cmd_run, "enqueue": cmd_enqueue, "worker": cmd_worker, "status": cmd_status, "plan": cmd_plan,
     "stop": lambda a: _set_paused(a, True), "resume": lambda a: _set_paused(a, False), "policy": cmd_policy,
     "dashboard": cmd_dashboard, "ideas": cmd_ideas, "approve": cmd_approve,
     "backup": cmd_backup, "verify-backup": cmd_verify_backup,
     "review": cmd_review}[a.cmd](a)


if __name__ == "__main__":
    main()
