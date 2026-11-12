"""WONDERLAND CEO AGENT — the orchestrator.

It does three things and nothing creative:

1. **Plans**: turns the schedule in ``studio.yaml`` into episodes (one per publishing slot, for
   today and the buffer days) and gives each a chain of tasks, one per department.
2. **Runs the queue**: takes the next runnable task, hands it to its department, stores the
   department's report, and reacts — retry with backoff, park as blocked, fail and move on,
   or order a new story when quality control rejects an episode.
3. **Recovers**: all state is in the database, so after a crash or a restart the next
   ``tick`` simply continues. Tasks left "running" by a dead worker go back to the queue.

Episode task chain (``<episode>:<kind>``), each owned by one department::

    script → storyboard → animation → sound → edit → qa → seo → compliance → publish → verify

A failure in one episode never stops the others: only its own downstream tasks are cancelled.
Daily company tasks (``day-YYYYMMDD:<kind>``): research, analytics, improve, report, health, backup.
"""

from __future__ import annotations

import importlib
import os
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .db import DB, iso, parse_iso
from .protocol import AgentReport, BlockedError, QualityError, classify

# kind → (agent name, "module:function"). Departments are imported on first use so one broken
# department cannot stop the others from loading.
DEPARTMENTS: dict[str, tuple[str, str]] = {
    "research": ("research", "wonderland.departments.research:handle_research"),
    "script": ("story", "wonderland.departments.production:handle_script"),
    "storyboard": ("storyboard", "wonderland.departments.production:handle_storyboard"),
    "animation": ("animation", "wonderland.departments.production:handle_animation"),
    "sound": ("audio", "wonderland.departments.production:handle_sound"),
    "edit": ("editing", "wonderland.departments.production:handle_edit"),
    "qa": ("quality", "wonderland.departments.production:handle_qa"),
    "seo": ("seo", "wonderland.departments.seo:handle_seo"),
    "compliance": ("compliance", "wonderland.departments.gate:handle_compliance"),
    "publish": ("publishing", "wonderland.departments.publishing:handle_publish"),
    "verify": ("publishing", "wonderland.departments.publishing:handle_verify"),
    "analytics": ("analytics", "wonderland.departments.analytics:handle_analytics"),
    "improve": ("improvement", "wonderland.departments.improvement:handle_improve"),
    "report": ("reporting", "wonderland.ops:handle_report"),
    "health": ("infrastructure", "wonderland.ops:handle_health"),
    "backup": ("infrastructure", "wonderland.ops:handle_backup"),
}
EPISODE_CHAIN = ("script", "storyboard", "animation", "sound", "edit", "qa", "seo", "compliance", "publish", "verify")
PRODUCTION_KINDS = ("script", "storyboard", "animation", "sound", "edit", "qa", "seo", "compliance")
CYCLE_STAGE = {"script": "script", "storyboard": "storyboard", "animation": "animation", "sound": "sound", "edit": "edit", "qa": "qa",
               "seo": "seo", "compliance": "compliance", "publish": "publish", "verify": "publish", "research": "research"}
DAILY = (("research", 10), ("health", 5), ("analytics", 60), ("improve", 70), ("report", 80), ("backup", 90))
LEASE_SECONDS = {"animation": 3600, "publish": 3600}
RECHECK_BLOCKED = timedelta(minutes=30)


class Studio:
    """Everything a department needs: configuration, the database, the clock and the folders."""

    def __init__(self, root: Path | None = None, state: Path | None = None, now_fn=None, cfg: dict | None = None, universe: dict | None = None):
        self.root = Path(root or config.ROOT)
        self.cfg = cfg or config.load_studio(self.root)
        self.universe = universe or config.load_universe(self.root)
        self.state = Path(state) if state else config.state_dir(self.cfg)
        self.state.mkdir(parents=True, exist_ok=True)
        self.db = DB(self.state / "wonderland.db")
        self.tz = ZoneInfo(self.cfg.get("timezone", "UTC"))
        self._now = now_fn
        self._desk = None
        self.owner = f"worker-{os.getpid()}"

    # -- clock ---------------------------------------------------------------------------
    def now(self) -> datetime:
        return (self._now() if self._now else datetime.now(timezone.utc)).astimezone(timezone.utc)

    def local_day(self, when: datetime | None = None) -> date:
        return (when or self.now()).astimezone(self.tz).date()

    def local_time(self, day: date, hhmm: str) -> datetime:
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime.combine(day, dtime(h, m), tzinfo=self.tz).astimezone(timezone.utc)

    # -- shared services -----------------------------------------------------------------
    @property
    def desk(self):
        if self._desk is None:
            from . import pipeline
            self._desk = pipeline.make_desk(self.cfg, self.state)
        return self._desk

    def episode_dir(self, ep_id: str) -> Path:
        path = self.state / "episodes" / ep_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def publish_mode(self) -> str:
        return self.cfg.get("publishing", {}).get("mode", "off")

    def notify(self, level: str, title: str, body: str, fingerprint: str | None = None) -> None:
        self.db.notify(level, title, body, self.now(), fingerprint)
        self.db.log("warning" if level != "info" else "info", "notify", title, self.now(), body=body[:500])

    # -- planning ------------------------------------------------------------------------
    def slots(self) -> list[dict]:
        return sorted(self.cfg.get("slots", []), key=lambda s: s["id"])

    def plan(self) -> dict:
        """Create the episodes and tasks that should exist right now. Idempotent."""
        now = self.now()
        today = self.local_day(now)
        buffer_days = int(self.cfg.get("buffer_days", 2))
        lead = timedelta(minutes=int(self.cfg.get("publishing", {}).get("lead_minutes", 20)))
        max_unpublished = int(self.cfg.get("max_unpublished", 12))
        retry = self.cfg.get("retry", {})
        created_eps, created_tasks = [], 0
        cycle = self.cfg.get("cycle", {})

        with self.db.tx():
            for kind, prio in DAILY:
                key = f"day-{today:%Y%m%d}:{kind}"
                at = self.local_time(today, cycle.get(kind, cycle.get("research", "01:00") if kind in ("research", "health") else cycle.get("publish", "08:00")))
                created_tasks += self.db.add_task(key, DEPARTMENTS[kind][0], kind, now, priority=prio, cycle_at=at,
                                                  max_attempts=int(retry.get("max_attempts", 4)))
            backlog = self.db.scalar("SELECT COUNT(*) FROM episodes WHERE status IN ('planned','in_production','produced')")
            for offset in range(buffer_days + 1):
                day = today + timedelta(days=offset)
                for slot in self.slots():
                    publish_at = self.local_time(day, slot["time"])
                    if publish_at <= now + lead:
                        continue                                    # this slot has passed (or is too close to make)
                    ep_id = f"ep-{day:%Y%m%d}-s{slot['id']}"
                    if self.db.episode(ep_id):
                        continue
                    if backlog >= max_unpublished:
                        self.db.log("info", "ceo", f"planning paused: {backlog} unpublished episodes (limit {max_unpublished})", now)
                        break
                    self.db.add_episode(ep_id, f"{day:%Y-%m-%d}", int(slot["id"]), slot.get("kind", ""), publish_at, now)
                    cycle_day = max(today, day - timedelta(days=buffer_days))
                    created_tasks += self._chain(ep_id, cycle_day, now)
                    created_eps.append(ep_id)
                    backlog += 1
        if created_eps:
            self.db.log("info", "ceo", f"planned {len(created_eps)} episode(s)", now, episodes=created_eps)
        return {"episodes": created_eps, "tasks": created_tasks}

    def _chain(self, ep_id: str, cycle_day: date, now: datetime) -> int:
        cycle = self.cfg.get("cycle", {})
        retry = int(self.cfg.get("retry", {}).get("max_attempts", 4))
        n, prev = 0, f"~day-{cycle_day:%Y%m%d}:research"
        for i, kind in enumerate(EPISODE_CHAIN):
            at = self.local_time(cycle_day, cycle.get(CYCLE_STAGE[kind], "02:00"))
            n += self.db.add_task(f"{ep_id}:{kind}", DEPARTMENTS[kind][0], kind, now, episode_id=ep_id, depends_on=[prev],
                                  priority=20 + i, cycle_at=at, max_attempts=retry)
            prev = f"{ep_id}:{kind}"
        return n

    # -- the queue -----------------------------------------------------------------------
    def tick(self, catch_up: bool = False, kinds: list[str] | None = None) -> dict | None:
        """Run one task. Returns a summary, or None when nothing is runnable right now."""
        now = self.now()
        self.db.release_expired(now)
        self.db.unblock_due(now)
        task = self.db.claim(self.owner, now, respect_cycle=not catch_up, kinds=kinds)
        if task is None:
            return None
        if task["kind"] in LEASE_SECONDS:
            self.db.conn.execute("UPDATE tasks SET lease_until=? WHERE id=?", (iso(now + timedelta(seconds=LEASE_SECONDS[task["kind"]])), task["id"]))
        ep = self.db.episode(task["episode_id"]) if task["episode_id"] else None
        if ep and ep["status"] == "planned" and task["kind"] in PRODUCTION_KINDS:
            self.db.update_episode(ep["id"], now, status="in_production")
        agent = task["agent"]
        t0 = time.time()
        try:
            handler = self._handler(task["kind"])
            report = handler(self, task, ep)
            if not isinstance(report, AgentReport):
                raise TypeError(f"department {agent} returned {type(report).__name__}, not an AgentReport")
        except BlockedError as exc:
            report = AgentReport(agent, task["key"], "blocked", errors=[str(exc)], next_action=exc.needs)
        except Exception as exc:  # noqa: BLE001 - every department failure becomes a report, never a crash
            report = self._failure(task, exc)
        seconds = round(time.time() - t0, 2)
        now = self.now()
        self.db.add_report(report.as_dict(), now, task_key=task["key"], episode_id=task["episode_id"], seconds=seconds)
        self._react(task, ep, report, now)
        return {"task": task["key"], "agent": agent, "status": report.status, "seconds": seconds, "errors": report.errors[:2], "next_action": report.next_action}

    def _handler(self, kind: str):
        module, func = DEPARTMENTS[kind][1].split(":")
        return getattr(importlib.import_module(module), func)

    def _failure(self, task: dict, exc: Exception) -> AgentReport:
        cls = classify(exc)
        detail = f"{type(exc).__name__}: {exc}"
        self.db.log("error", task["agent"], f"{task['key']} raised {detail}", self.now(), error_class=cls,
                    trace=traceback.format_exc(limit=6)[-1500:])
        report = AgentReport(task["agent"], task["key"], "failed", errors=[detail], output={"error_class": cls})
        if isinstance(exc, QualityError):
            report.next_action = "regenerate"
        return report

    def _react(self, task: dict, ep: dict | None, report: AgentReport, now: datetime) -> None:
        retry_cfg = self.cfg.get("retry", {})
        if report.status in ("success", "skipped"):
            self.db.finish_task(task["id"], {"status": report.status, "output": report.output, "next_action": report.next_action}, now)
            if report.status == "skipped" and ep and task["kind"] in PRODUCTION_KINDS:
                self.db.update_episode(ep["id"], now, status="skipped", error="; ".join(report.errors) or report.next_action)
                self.db.cancel_downstream(task["key"], now, "episode skipped")
            if report.next_action.startswith("recheck:"):          # e.g. verify waiting for the publish time
                self.db.conn.execute("UPDATE tasks SET status='pending', not_before=?, attempts=0, finished_at=NULL WHERE id=?",
                                     (report.next_action.split(":", 1)[1], task["id"]))
            return
        if report.status == "blocked":
            self.db.block_task(task["id"], "; ".join(report.errors) or report.next_action, now + RECHECK_BLOCKED)
            self.notify("action", f"Blocked: {task['key']}", f"{'; '.join(report.errors)}\nNeeded: {report.next_action}", fingerprint=f"blocked:{task['kind']}:{report.next_action}")
            return
        # failed
        cls = report.output.get("error_class", "permanent")
        error = "; ".join(str(e) for e in report.errors)
        if report.next_action == "regenerate" and ep:
            if self._regenerate(ep, task, error, now):
                return
            cls = "permanent"
        max_attempts = task["max_attempts"] if cls == "transient" else (2 if cls == "unknown" else 1)
        if task["attempts"] < max_attempts:
            base = float(retry_cfg.get("base_delay_seconds", 30))
            delay = min(float(retry_cfg.get("max_delay_seconds", 1800)), base * (2 ** (task["attempts"] - 1)))
            self.db.retry_task(task["id"], cls, error, now + timedelta(seconds=delay))
            self.db.log("warning", "ceo", f"{task['key']} will retry in {delay:.0f}s ({task['attempts']}/{max_attempts})", now, error=error[:300])
            return
        self.db.fail_task(task["id"], cls, error, now)
        cancelled = self.db.cancel_downstream(task["key"], now, f"{task['key']} failed")
        if ep and task["kind"] in PRODUCTION_KINDS:
            self.db.update_episode(ep["id"], now, status="failed", error=f"{task['kind']}: {error}"[:1000])
        self.notify("error", f"Failed: {task['key']}", f"{error}\nCancelled: {', '.join(cancelled) or 'nothing'}", fingerprint=f"failed:{task['key']}")

    def _regenerate(self, ep: dict, task: dict, error: str, now: datetime) -> bool:
        """Quality control rejected the episode: order a new story (bounded), keep the publishing slot."""
        limit = int(self.cfg.get("story", {}).get("max_regenerations", 2))
        if ep["attempt"] >= limit:
            self.db.log("error", "ceo", f"{ep['id']} failed quality control {ep['attempt'] + 1} times; giving up", now, error=error[:300])
            return False
        with self.db.tx():
            self.db.update_episode(ep["id"], now, attempt=ep["attempt"] + 1, status="in_production", story=None, story_report=None, signature=None, script=None,
                                   title=None, qa=None, metadata=None, compliance=None, production=None, video_path=None, video_sha256=None,
                                   error=f"regenerating after: {error}"[:1000])
            keys = [f"{ep['id']}:{k}" for k in PRODUCTION_KINDS]
            self.db.conn.execute(f"UPDATE tasks SET status='pending', attempts=0, error=NULL, error_class=NULL, result=NULL, not_before=NULL, lease_owner=NULL, "
                                 f"lease_until=NULL, finished_at=NULL WHERE key IN ({','.join('?' * len(keys))})", tuple(keys))
        self.db.log("warning", "ceo", f"{ep['id']}: quality control failed, ordering story #{ep['attempt'] + 2}", now, error=error[:300])
        return True

    def run_cycle(self, catch_up: bool = True, max_seconds: float | None = None, kinds: list[str] | None = None, log=None) -> dict:
        """Plan, then work the queue until nothing is runnable (or the time budget is spent)."""
        say = log or (lambda *_: None)
        t0 = time.time()
        planned = self.plan()
        done: list[dict] = []
        while True:
            if max_seconds is not None and time.time() - t0 > max_seconds:
                say("time budget reached; the rest continues on the next run")
                break
            step = self.tick(catch_up=catch_up, kinds=kinds)
            if step is None:
                break
            done.append(step)
            say(f"{step['status']:8s} {step['task']}  ({step['seconds']}s)" + (f"  {step['errors'][0][:120]}" if step["errors"] else ""))
        counts: dict[str, int] = {}
        for d in done:
            counts[d["status"]] = counts.get(d["status"], 0) + 1
        self.db.set("last_cycle", {"at": iso(self.now()), "planned": planned, "ran": len(done), "by_status": counts, "seconds": round(time.time() - t0, 1)}, self.now())
        return {"planned": planned, "ran": len(done), "by_status": counts, "steps": done, "seconds": round(time.time() - t0, 1)}

    # -- owner actions -------------------------------------------------------------------
    def approve(self, ep_id: str, by: str = "owner") -> dict:
        ep = self.db.episode(ep_id)
        if not ep:
            raise KeyError(f"no episode {ep_id}")
        if ep["status"] != "produced":
            raise ValueError(f"{ep_id} is '{ep['status']}'; only produced episodes can be approved")
        now = self.now()
        self.db.update_episode(ep_id, now, approved=True, approved_by=by, approved_at=now, approved_sha256=ep["video_sha256"])
        self.db.conn.execute("UPDATE tasks SET status='pending', not_before=NULL WHERE key=? AND status='blocked'", (f"{ep_id}:publish",))
        self.db.log("info", "owner", f"approved {ep_id}", now, by=by)
        return self.db.episode(ep_id)

    def reject(self, ep_id: str, reason: str, by: str = "owner") -> dict:
        ep = self.db.episode(ep_id)
        if not ep:
            raise KeyError(f"no episode {ep_id}")
        if ep["status"] in ("uploaded", "scheduled", "published"):
            raise ValueError(f"{ep_id} is already on YouTube ({ep['status']}); remove it in YouTube Studio")
        now = self.now()
        self.db.update_episode(ep_id, now, status="rejected", approved=False, error=f"rejected by {by}: {reason}"[:1000])
        self.db.conn.execute("UPDATE tasks SET status='cancelled', error=?, finished_at=? WHERE episode_id=? AND status IN ('pending','blocked')",
                             (f"rejected: {reason}"[:500], iso(now), ep_id))
        self.db.log("info", "owner", f"rejected {ep_id}: {reason}", now, by=by)
        return self.db.episode(ep_id)

    # -- the completed / pending / blocked list ---------------------------------------------
    def worklist(self) -> dict:
        t = self.db.tasks
        return {
            "completed": [{"task": r["key"], "at": r["finished_at"]} for r in t("status='done'", order="finished_at DESC")[:40]],
            "pending": [{"task": r["key"], "after": r["not_before"] or r["cycle_at"], "attempts": r["attempts"]} for r in t("status IN ('pending','running')")],
            "blocked": [{"task": r["key"], "reason": r["error"]} for r in t("status='blocked'")],
            "failed": [{"task": r["key"], "error": r["error"], "class": r["error_class"]} for r in t("status='failed'", order="finished_at DESC")[:40]],
        }


def publish_time(ep: dict) -> datetime:
    return parse_iso(ep["publish_at"])
