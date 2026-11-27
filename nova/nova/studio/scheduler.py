"""ENGINE 07: Autonomous scheduling.

A. Content scheduler: a calendar of content (date, time, timezone, platform, category, status),
   recurring themes, and posting-time guidance (general guidance, not the user's analytics).
B. Production task scheduler: persistent jobs (once / daily / weekly / interval) in a named IANA
   timezone, with priority, dependencies, retries and failure notifications.

Jobs live in SQLite, so they survive restarts. A job is claimed with an atomic lease (UPDATE ...
WHERE lease is free and next_run is unchanged) and every run is a row with a UNIQUE (job,
scheduled time, attempt) key, so two workers or a restart can never run the same occurrence
twice. A run is "succeeded" only after its production finished and passed quality assurance."""
from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .db import Store, dumps, loads, new_id, now

LEASE_S = 3 * 3600
POSTING_GUIDANCE = {  # general industry guidance in local time; replaced by real analytics when connected
    "tiktok": ["12:00", "19:00", "21:00"], "instagram_reels": ["11:00", "19:00"],
    "youtube_shorts": ["12:00", "18:00"], "youtube": ["15:00", "19:00"], "facebook": ["13:00", "20:00"],
}


def _parse_hm(s: str) -> time:
    h, m = s.split(":")
    t = time(int(h), int(m))
    return t


def next_run(schedule: dict, tz: str, after: datetime) -> datetime | None:
    """Next occurrence strictly after `after` (UTC aware), returned in UTC."""
    z = ZoneInfo(tz)
    kind = schedule.get("type")
    local_after = after.astimezone(z)
    if kind == "once":
        at = datetime.fromisoformat(schedule["at"])
        at = at.replace(tzinfo=z) if at.tzinfo is None else at
        return at.astimezone(timezone.utc) if at.astimezone(timezone.utc) > after - timedelta(days=3650) else None
    if kind == "interval":
        minutes = int(schedule["minutes"])
        if minutes < 1:
            raise ValueError("interval must be at least 1 minute")
        return after + timedelta(minutes=minutes)
    if kind in ("daily", "weekly"):
        t = _parse_hm(schedule["time"])
        days = set(schedule.get("days", range(7))) if kind == "weekly" else set(range(7))
        if not days or not days <= set(range(7)):
            raise ValueError("weekly days must be 0 (Monday) to 6 (Sunday)")
        d = local_after.date()
        for i in range(8):
            cand_date = d + timedelta(days=i)
            cand = datetime.combine(cand_date, t, tzinfo=z)
            if cand.weekday() in days and cand > local_after:
                return cand.astimezone(timezone.utc)
        return None
    raise ValueError("schedule type must be once, daily, weekly or interval")


class Scheduler:
    def __init__(self, store: Store, run_production, poll_s: float = 15.0) -> None:
        """run_production(payload, job_run_id, idempotency_key) -> production dict (blocking)."""
        self.store, self.run_production, self.poll_s = store, run_production, poll_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- jobs ------------------------------------------------------------------------------
    def create(self, name: str, payload: dict, schedule: dict, tz: str, priority: int = 5, max_retries: int = 1,
               depends_on: str | None = None, idempotency_key: str | None = None, kind: str = "production") -> dict:
        ZoneInfo(tz)  # raises for an unknown timezone
        if idempotency_key:
            existing = self.store.one("SELECT * FROM scheduled_jobs WHERE idempotency_key=?", (idempotency_key,))
            if existing:
                return self._row(existing) | {"duplicate": True}
        nxt = next_run(schedule, tz, datetime.now(timezone.utc) - (timedelta(seconds=1) if schedule.get("type") == "once" else timedelta()))
        row = {"id": new_id(), "name": name[:200], "kind": kind, "payload": dumps(payload), "schedule": dumps(schedule),
               "timezone": tz, "next_run_utc": nxt.isoformat() if nxt else None, "enabled": 1,
               "priority": int(priority), "max_retries": int(max_retries), "depends_on": depends_on,
               "idempotency_key": idempotency_key, "lease_until": None, "last_status": "scheduled", "created_at": now()}
        self.store.insert("scheduled_jobs", row)
        return self.get(row["id"])

    def get(self, job_id: str) -> dict | None:
        r = self.store.one("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,))
        return self._row(r) if r else None

    def list(self) -> list[dict]:
        return [self._row(r) for r in self.store.all("SELECT * FROM scheduled_jobs ORDER BY next_run_utc IS NULL, next_run_utc")]

    def set_enabled(self, job_id: str, enabled: bool) -> dict:
        self.store.execute("UPDATE scheduled_jobs SET enabled=? WHERE id=?", (1 if enabled else 0, job_id))
        return self.get(job_id)

    def delete(self, job_id: str) -> None:
        self.store.execute("UPDATE scheduled_jobs SET enabled=0, next_run_utc=NULL, last_status='deleted' WHERE id=?",
                           (job_id,))

    def runs(self, job_id: str | None = None, limit: int = 100) -> list[dict]:
        if job_id:
            return self.store.all("SELECT * FROM job_runs WHERE job_id=? ORDER BY started_at DESC LIMIT ?", (job_id, limit))
        return self.store.all("SELECT * FROM job_runs ORDER BY started_at DESC LIMIT ?", (limit,))

    def _row(self, r: dict) -> dict:
        r = dict(r)
        r["payload"], r["schedule"] = loads(r["payload"]), loads(r["schedule"])
        if r.get("next_run_utc"):
            r["next_run_local"] = datetime.fromisoformat(r["next_run_utc"]).astimezone(ZoneInfo(r["timezone"])).isoformat()
        return r

    # --- execution -------------------------------------------------------------------------
    def _dependency_ok(self, job: dict) -> bool:
        if not job.get("depends_on"):
            return True
        last = self.store.one("SELECT status, finished_at FROM job_runs WHERE job_id=? ORDER BY finished_at DESC LIMIT 1",
                              (job["depends_on"],))
        if not last or last["status"] != "succeeded":
            return False
        return datetime.fromisoformat(last["finished_at"]) > datetime.fromisoformat(job["next_run_utc"]) - timedelta(hours=24)

    def claim_due(self, at: datetime | None = None) -> list[dict]:
        at = at or datetime.now(timezone.utc)
        due = self.store.all("SELECT * FROM scheduled_jobs WHERE enabled=1 AND next_run_utc IS NOT NULL AND "
                             "next_run_utc<=? AND (lease_until IS NULL OR lease_until<?) ORDER BY priority, next_run_utc",
                             (at.isoformat(), at.isoformat()))
        claimed = []
        for j in due:
            if not self._dependency_ok(j):
                continue
            lease = (at + timedelta(seconds=LEASE_S)).isoformat()
            n = self.store.execute("UPDATE scheduled_jobs SET lease_until=? WHERE id=? AND next_run_utc=? AND "
                                   "(lease_until IS NULL OR lease_until<?)", (lease, j["id"], j["next_run_utc"], at.isoformat()))
            if n == 1:
                claimed.append(self._row(j))
        return claimed

    def execute(self, job: dict) -> dict:
        """Run one claimed occurrence (with retries) and move the job to its next time."""
        scheduled_for = job["next_run_utc"]
        result = {"job_id": job["id"], "scheduled_for": scheduled_for, "attempts": []}
        status = "failed"
        for attempt in range(1, job["max_retries"] + 2):
            run_id = new_id()
            try:
                self.store.insert("job_runs", {"id": run_id, "job_id": job["id"], "scheduled_for": scheduled_for,
                                               "attempt": attempt, "started_at": now(), "status": "running"})
            except Exception:  # UNIQUE: this occurrence was already run elsewhere
                result["duplicate"] = True
                return result
            key = f"job:{job['id']}:{scheduled_for}"
            try:
                prod = self.run_production(job["payload"], run_id, f"{key}:{attempt}")
                ok = prod.get("status") == "completed" and prod.get("qa_passed")
                err = None if ok else (prod.get("error") or "quality check did not pass")
            except Exception as exc:
                prod, ok, err = {}, False, f"{type(exc).__name__}: {exc}"
            self.store.execute("UPDATE job_runs SET finished_at=?, status=?, production_id=?, error=? WHERE id=?",
                               (now(), "succeeded" if ok else "failed", prod.get("id"), err, run_id))
            result["attempts"].append({"run_id": run_id, "ok": ok, "production_id": prod.get("id"), "error": err})
            if ok:
                status = "succeeded"
                break
        if status != "succeeded":
            self.store.notify(f"Scheduled job '{job['name']}' failed at {scheduled_for}: {result['attempts'][-1]['error']}",
                              "error", job_id=job["id"])
        after = datetime.fromisoformat(scheduled_for)
        nxt = None if job["schedule"]["type"] == "once" else next_run(job["schedule"], job["timezone"], max(after, datetime.now(timezone.utc)))
        self.store.execute("UPDATE scheduled_jobs SET next_run_utc=?, lease_until=NULL, last_status=? WHERE id=?",
                           (nxt.isoformat() if nxt else None, status, job["id"]))
        result["status"] = status
        return result

    def tick(self) -> list[dict]:
        return [self.execute(j) for j in self.claim_due()]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:  # keep the loop alive; record the failure
                    self.store.notify(f"scheduler loop error: {exc}", "error")
                self._stop.wait(self.poll_s)

        self._thread = threading.Thread(target=loop, name="nova-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


# --- content calendar ------------------------------------------------------------------------
class Calendar:
    STATUSES = ("idea", "scripted", "scheduled", "produced", "published", "skipped")

    def __init__(self, store: Store) -> None:
        self.store = store

    def add(self, day: str, title: str, tz: str, time_: str | None = None, platform: str | None = None,
            category: str | None = None, theme: str | None = None, notes: str | None = None) -> dict:
        ZoneInfo(tz)
        date.fromisoformat(day)
        if time_:
            _parse_hm(time_)
        row = {"id": new_id(), "date": day, "time": time_, "timezone": tz, "platform": platform, "category": category,
               "title": title[:200], "theme": theme, "status": "idea", "notes": notes, "created_at": now()}
        self.store.insert("content_calendar", row)
        return row

    def recurring(self, theme: str, title_template: str, start: str, weeks: int, weekdays: list[int], tz: str,
                  time_: str | None = None, platform: str | None = None, category: str | None = None) -> list[dict]:
        d0 = date.fromisoformat(start)
        out = []
        for i in range(weeks * 7):
            d = d0 + timedelta(days=i)
            if d.weekday() in weekdays:
                out.append(self.add(d.isoformat(), title_template.format(date=d.isoformat(), n=len(out) + 1), tz,
                                    time_, platform, category, theme))
        return out

    def list(self, start: str | None = None, end: str | None = None) -> list[dict]:
        if start and end:
            return self.store.all("SELECT * FROM content_calendar WHERE date BETWEEN ? AND ? ORDER BY date, time", (start, end))
        return self.store.all("SELECT * FROM content_calendar ORDER BY date, time")

    def update(self, entry_id: str, **fields) -> dict:
        allowed = {k: v for k, v in fields.items() if k in ("status", "title", "time", "platform", "category", "notes",
                                                            "production_id", "job_id") and v is not None}
        if "status" in allowed and allowed["status"] not in self.STATUSES:
            raise ValueError(f"status must be one of {self.STATUSES}")
        for k, v in allowed.items():
            self.store.execute(f"UPDATE content_calendar SET {k}=? WHERE id=?", (v, entry_id))
        return self.store.one("SELECT * FROM content_calendar WHERE id=?", (entry_id,))

    @staticmethod
    def recommend_times(platform: str) -> dict:
        return {"platform": platform, "times_local": POSTING_GUIDANCE.get(platform, ["12:00", "19:00"]),
                "basis": "general guidance; connect analytics for times measured on your own audience"}
