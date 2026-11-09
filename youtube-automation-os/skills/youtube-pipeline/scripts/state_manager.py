#!/usr/bin/env python3
"""Inspect and repair pipeline state (local only; no API calls).

Commands:
  list   [--since 24h|7d|YYYY-MM-DD] [--status STATUS]   jobs, newest first ("yesterday's uploads": --since 2d)
  show   JOB_ID                                          full job record with history
  quota                                                  today's estimated quota usage (Pacific date)
  resolve JOB_ID --video-id ID                           after checking YouTube Studio by hand, record the
                                                         video that an uncertain upload produced
  unlock JOB_ID                                          remove a stale lock left by a killed process
  reset  JOB_ID --confirm [--forget-upload]              delete a job's local state (the video on YouTube is untouched)

Examples:
  python skills/youtube-pipeline/scripts/state_manager.py list --since 2d
  python skills/youtube-pipeline/scripts/state_manager.py show 3f2a9c1d0b7e4a55
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.exceptions import ConfirmationRequired, ValidationError  # noqa: E402
from src.state import STATUSES  # noqa: E402


def parse_since(value: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    m = re.fullmatch(r"(\d+)([hd])", value.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return now - (timedelta(hours=n) if unit == "h" else timedelta(days=n))
    try:
        d = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"--since must be like 24h, 7d or YYYY-MM-DD (got {value!r})") from exc
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def summarize(job: dict) -> dict:
    return {k: job.get(k) for k in ("job_id", "status", "video_id", "title", "updated_at", "created_at", "file")}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    cli.add_output_flags(common)
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", parents=[common])
    ls.add_argument("--since")
    ls.add_argument("--status", choices=STATUSES)
    sh = sub.add_parser("show", parents=[common])
    sh.add_argument("job_id")
    sub.add_parser("quota", parents=[common])
    rs = sub.add_parser("resolve", parents=[common])
    rs.add_argument("job_id")
    rs.add_argument("--video-id", required=True)
    ul = sub.add_parser("unlock", parents=[common])
    ul.add_argument("job_id")
    rr = sub.add_parser("reset", parents=[common])
    rr.add_argument("job_id")
    rr.add_argument("--confirm", action="store_true")
    rr.add_argument("--forget-upload", action="store_true", help="Also remove the file from the duplicate-upload index")
    args = p.parse_args()
    rt = cli.runtime()
    store = rt.store

    if args.cmd == "quota":
        cli.emit(rt.quota.report(), args.json, lambda d: "\n".join(
            [f"Quota estimate for {d['date_pacific']} (Pacific):"] +
            [f"  {k}: used ~{v['used_estimate']} / {v['daily_limit'] if v['daily_limit'] is not None else '∞'} {v['unit']}" + (" EXHAUSTED" if v["exhausted"] else "") for k, v in d["buckets"].items()] +
            [d["note"]]))
        return 0

    if args.cmd == "list":
        jobs = store.list_jobs()
        if args.since:
            cutoff = parse_since(args.since)
            jobs = [j for j in jobs if datetime.fromisoformat(j.get("updated_at", "1970-01-01T00:00:00+00:00")) >= cutoff]
        if args.status:
            jobs = [j for j in jobs if j.get("status") == args.status]
        rows = [summarize(j) for j in jobs]
        cli.emit(rows, args.json, lambda rs: "\n".join(f"{r['updated_at']}  {r['job_id']}  {r['status']:<18} {r['video_id'] or '-':<12} {r['title']}" for r in rs) or "No jobs.")
        return 0

    job = store.load(args.job_id)
    if job is None:
        raise ValidationError(f"No job {args.job_id} in {store.jobs_dir}")

    if args.cmd == "show":
        cli.emit(job, True)
        return 0
    if args.cmd == "resolve":
        if job["status"] not in ("UPLOAD_UNCERTAIN", "NEEDS_MANUAL_CHECK", "FAILED", "UPLOADING"):
            raise ValidationError(f"Job is {job['status']}; resolve is only for uncertain/failed uploads")
        store.record_upload(job["file_sha256"], args.video_id, job["job_id"], job.get("title", ""))
        store.transition(job, "UPLOADED", "resolved manually after checking YouTube Studio", video_id=args.video_id, resumable_uri=None)
        print(f"Job {job['job_id']} now UPLOADED as {args.video_id}. Re-run the pipeline to apply thumbnail/verification.")
        return 0
    if args.cmd == "unlock":
        lock = store.jobs_dir / f"{args.job_id}.lock"
        if lock.exists():
            lock.unlink()
            print(f"Removed {lock}")
        else:
            print("No lock present.")
        return 0
    if args.cmd == "reset":
        if not args.confirm:
            raise ConfirmationRequired("reset deletes local job state; re-run with --confirm")
        store.job_path(args.job_id).unlink()
        if args.forget_upload and job.get("file_sha256"):
            idx_path = store.index_path
            if idx_path.exists():
                idx = json.loads(idx_path.read_text(encoding="utf-8"))
                idx.pop(job["file_sha256"], None)
                idx_path.write_text(json.dumps(idx, indent=2), encoding="utf-8")
        print(f"Deleted local state for {args.job_id}. Nothing on YouTube was changed.")
        return 0
    return 1


if __name__ == "__main__":
    cli.run(main)
