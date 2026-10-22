"""Autopilot governance and content planning.

The policy file (JSON, next to the queue database by default) is the owner's control panel:

- paused:              emergency stop. Workers stop claiming new jobs (a running job finishes its
                       current production; nothing new starts). `apex.cli stop` / `resume` flip it.
- max_jobs_per_day:    hard cap on jobs created per UTC day, counted from the queue itself.
- allowed_topics:      if non-empty, a spec's topic must contain one of these keywords.
- prohibited_topics:   a spec whose topic contains any of these keywords is refused.
- require_approval:    plan entries are only enqueued when they carry "approved": true.

Full autopilot never means unlimited authority: every limit is enforced here, before a job exists.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pydantic import BaseModel, Field

from .jobs import JobQueue
from .models import ProductionSpec


class AutopilotPolicy(BaseModel):
    paused: bool = False
    max_jobs_per_day: int = Field(3, ge=0, le=100)
    allowed_topics: list[str] = Field(default_factory=list)
    prohibited_topics: list[str] = Field(default_factory=list)
    require_approval: bool = True


def load_policy(path: Path) -> AutopilotPolicy:
    """A missing file means the safe defaults: approval required, 3 jobs a day, not paused."""
    p = Path(path)
    return AutopilotPolicy.model_validate_json(p.read_text()) if p.exists() else AutopilotPolicy()


def save_policy(policy: AutopilotPolicy, path: Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(policy.model_dump_json(indent=2))
    tmp.replace(p)  # atomic: a worker never reads a half-written policy


def topic_violations(policy: AutopilotPolicy, spec: ProductionSpec) -> list[str]:
    topic = spec.topic.lower()
    problems = [f"topic contains prohibited keyword {k!r}" for k in policy.prohibited_topics if k.lower() in topic]
    if policy.allowed_topics and not any(k.lower() in topic for k in policy.allowed_topics):
        problems.append("topic matches none of the allowed topics")
    return problems


def jobs_created_today(queue: JobQueue, now: float | None = None) -> int:
    now = queue.clock() if now is None else now
    day = dt.datetime.fromtimestamp(now, dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    row = queue.db.execute("SELECT COUNT(*) n FROM jobs WHERE created_at >= ?", (day.timestamp(),)).fetchone()
    return row["n"]


def run_plan(plan: list[dict], queue: JobQueue, policy: AutopilotPolicy, base_dir: Path) -> list[dict]:
    """Enqueue the plan entries the policy allows. Returns one decision per entry.

    Each entry: {"id": str, "spec": path-or-object, "script": optional path, "project": optional path,
                 "approved": bool, "fps": int, "samples": int}.
    The entry id is the idempotency key, so re-running a plan never creates duplicates.
    """
    decisions = []
    if policy.paused:
        return [{"id": e.get("id"), "decision": "SKIPPED", "reason": "autopilot is paused (emergency stop)"}
                for e in plan]
    remaining = policy.max_jobs_per_day - jobs_created_today(queue)
    for entry in plan:
        eid = str(entry.get("id") or "").strip()
        if not eid:
            decisions.append({"id": None, "decision": "REJECTED", "reason": "entry has no id"})
            continue
        key = f"plan:{eid}"
        existing = queue.db.execute("SELECT id, state FROM jobs WHERE idempotency_key=?", (key,)).fetchone()
        if existing:
            decisions.append({"id": eid, "decision": "EXISTS", "job_id": existing["id"], "state": existing["state"]})
            continue
        if policy.require_approval and entry.get("approved") is not True:
            decisions.append({"id": eid, "decision": "WAITING_FOR_APPROVAL", "reason": 'set "approved": true'})
            continue
        spec_src = entry.get("spec")
        try:
            spec_data = spec_src if isinstance(spec_src, dict) else json.loads((base_dir / spec_src).read_text())
            spec = ProductionSpec.model_validate(spec_data)
        except Exception as e:  # noqa: BLE001  report any unreadable or invalid spec
            decisions.append({"id": eid, "decision": "REJECTED", "reason": f"invalid spec: {e}"[:300]})
            continue
        problems = topic_violations(policy, spec)
        if problems:
            decisions.append({"id": eid, "decision": "REJECTED", "reason": "; ".join(problems)})
            continue
        if remaining <= 0:
            decisions.append({"id": eid, "decision": "DEFERRED", "reason": f"daily limit {policy.max_jobs_per_day} reached"})
            continue
        payload = {"spec": spec.model_dump(), "project": str((base_dir / entry.get("project", f"out/{eid}")).resolve()),
                   "script": str((base_dir / entry["script"]).resolve()) if entry.get("script") else None,
                   "fps": int(entry.get("fps", 24)), "samples": int(entry.get("samples", 8))}
        job = queue.enqueue(key, "produce_video", payload)
        remaining -= 1
        decisions.append({"id": eid, "decision": "ENQUEUED", "job_id": job.id})
    return decisions
