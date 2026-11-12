"""The company's memory: one SQLite file (WAL), safe to kill at any moment.

Everything the studio knows lives here — the episode ledger, the persistent task queue, every
agent report, research, licences, costs, analytics, experiments, notifications and the log.
The dashboard and the reports read these tables and nothing else, so they can only show what
actually happened.

Times are UTC ISO strings (``2026-11-11T04:00:00Z``); JSON columns hold JSON text.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1

EPISODE_STATUSES = ("planned", "in_production", "produced", "uploaded", "scheduled", "published", "failed", "skipped", "rejected")
TASK_STATUSES = ("pending", "running", "done", "failed", "blocked", "cancelled")
TERMINAL = ("done", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY, day TEXT NOT NULL, slot INTEGER NOT NULL, kind TEXT, publish_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned', attempt INTEGER NOT NULL DEFAULT 0,
  category TEXT, format TEXT, title TEXT, signature TEXT, script TEXT, cast TEXT, story TEXT, story_report TEXT,
  dir TEXT, video_path TEXT, video_sha256 TEXT, duration REAL, production TEXT, qa TEXT, metadata TEXT, compliance TEXT,
  approved INTEGER NOT NULL DEFAULT 0, approved_by TEXT, approved_at TEXT, approved_sha256 TEXT,
  video_id TEXT, upload_job TEXT, uploaded_at TEXT, scheduled_for TEXT, published_at TEXT, verified_at TEXT, youtube_status TEXT,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS episodes_day ON episodes(day, slot);
CREATE INDEX IF NOT EXISTS episodes_status ON episodes(status);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, episode_id TEXT, agent TEXT NOT NULL, kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', depends_on TEXT NOT NULL DEFAULT '[]', priority INTEGER NOT NULL DEFAULT 50,
  cycle_at TEXT, not_before TEXT, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 4,
  lease_owner TEXT, lease_until TEXT, error_class TEXT, error TEXT, result TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status, priority);
CREATE INDEX IF NOT EXISTS tasks_episode ON tasks(episode_id);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, agent TEXT NOT NULL, task_id TEXT NOT NULL, task_key TEXT, episode_id TEXT,
  status TEXT NOT NULL, output TEXT NOT NULL, evidence TEXT NOT NULL, errors TEXT NOT NULL, next_action TEXT NOT NULL, seconds REAL);
CREATE INDEX IF NOT EXISTS reports_episode ON reports(episode_id);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL, source TEXT NOT NULL,
  message TEXT NOT NULL, data TEXT);
CREATE TABLE IF NOT EXISTS research (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'finding', topic TEXT NOT NULL, source TEXT NOT NULL, source_url TEXT,
  date TEXT NOT NULL, findings TEXT NOT NULL, confidence TEXT NOT NULL, recommended_action TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]',
  scores TEXT, fingerprint TEXT UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS licences (id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
  origin TEXT NOT NULL, license TEXT NOT NULL, evidence TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS licences_episode ON licences(episode_id);
CREATE TABLE IF NOT EXISTS costs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, day TEXT NOT NULL, episode_id TEXT, category TEXT NOT NULL,
  provider TEXT NOT NULL, units REAL NOT NULL DEFAULT 0, unit TEXT NOT NULL DEFAULT '', usd REAL NOT NULL DEFAULT 0, estimated INTEGER NOT NULL DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS analytics (video_id TEXT NOT NULL, day TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, fetched_at TEXT NOT NULL,
  PRIMARY KEY (video_id, day, metric));
CREATE TABLE IF NOT EXISTS channel_stats (day TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (day, metric));
CREATE TABLE IF NOT EXISTS experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, variable TEXT NOT NULL, variants TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running', hypothesis TEXT, metric TEXT, started_at TEXT NOT NULL, ended_at TEXT, result TEXT, decision TEXT);
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'log', delivered INTEGER NOT NULL DEFAULT 0, error TEXT, fingerprint TEXT);
CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL, period TEXT NOT NULL, title TEXT NOT NULL,
  body TEXT NOT NULL, data TEXT, UNIQUE (kind, period));
"""

JSON_EPISODE = ("cast", "story", "story_report", "production", "qa", "metadata", "compliance")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _loads(text, default=None):
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


class DB:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        if self.get("schema_version") is None:
            self.set("schema_version", SCHEMA_VERSION)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self):
        """BEGIN IMMEDIATE … COMMIT: one writer at a time, all or nothing."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, args: tuple = ()):
        row = self.conn.execute(sql, args).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ key/value
    def get(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return _loads(row[0], default) if row else default

    def set(self, key: str, value, now: datetime | None = None) -> None:
        self.conn.execute("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                          (key, json.dumps(value, default=str), iso(now or datetime.now(timezone.utc))))

    # ------------------------------------------------------------------ log
    def log(self, level: str, source: str, message: str, now: datetime | None = None, **data) -> None:
        self.conn.execute("INSERT INTO events(ts,level,source,message,data) VALUES(?,?,?,?,?)",
                          (iso(now or datetime.now(timezone.utc)), level, source, message, json.dumps(data, default=str) if data else None))

    # ------------------------------------------------------------------ episodes
    def _episode(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        for k in JSON_EPISODE:
            row[k] = _loads(row.get(k))
        row["approved"] = bool(row["approved"])
        return row

    def episode(self, ep_id: str) -> dict | None:
        return self._episode(self.one("SELECT * FROM episodes WHERE id=?", (ep_id,)))

    def episodes(self, where: str = "1=1", args: tuple = (), order: str = "publish_at") -> list[dict]:
        return [self._episode(r) for r in self.q(f"SELECT * FROM episodes WHERE {where} ORDER BY {order}", args)]

    def add_episode(self, ep_id: str, day: str, slot: int, kind: str, publish_at: datetime, now: datetime) -> bool:
        cur = self.conn.execute("INSERT OR IGNORE INTO episodes(id,day,slot,kind,publish_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                                (ep_id, day, slot, kind, iso(publish_at), iso(now), iso(now)))
        return cur.rowcount == 1

    def update_episode(self, ep_id: str, now: datetime | None = None, **fields) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(f'"{k}"=?')
            if k in JSON_EPISODE and v is not None:
                v = json.dumps(v, ensure_ascii=False, default=str)
            elif isinstance(v, bool):
                v = int(v)
            elif isinstance(v, datetime):
                v = iso(v)
            vals.append(v)
        cols.append("updated_at=?")
        vals.append(iso(now or datetime.now(timezone.utc)))
        self.conn.execute(f"UPDATE episodes SET {', '.join(cols)} WHERE id=?", (*vals, ep_id))

    def story_history(self, exclude: str | None = None) -> list[dict]:
        """Rows the story engine compares against, oldest first: every episode that got a script and was not thrown away."""
        rows = self.q("SELECT id, day, signature, format, script, \"cast\" FROM episodes WHERE signature IS NOT NULL AND status NOT IN ('failed','rejected','skipped') "
                      "AND id IS NOT ? ORDER BY publish_at", (exclude,))
        for r in rows:
            r["cast"] = _loads(r["cast"], [])
        return rows

    # ------------------------------------------------------------------ tasks
    def add_task(self, key: str, agent: str, kind: str, now: datetime, episode_id: str | None = None, depends_on: list[str] | None = None,
                 priority: int = 50, cycle_at: datetime | None = None, not_before: datetime | None = None, max_attempts: int = 4) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO tasks(key,episode_id,agent,kind,depends_on,priority,cycle_at,not_before,max_attempts,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (key, episode_id, agent, kind, json.dumps(depends_on or []), priority, iso(cycle_at) if cycle_at else None,
             iso(not_before) if not_before else None, max_attempts, iso(now)))
        return cur.rowcount == 1

    def task(self, key: str) -> dict | None:
        return self._task(self.one("SELECT * FROM tasks WHERE key=?", (key,)))

    def _task(self, row: dict | None) -> dict | None:
        if row:
            row["depends_on"] = _loads(row["depends_on"], [])
            row["result"] = _loads(row["result"])
        return row

    def tasks(self, where: str = "1=1", args: tuple = (), order: str = "id") -> list[dict]:
        return [self._task(r) for r in self.q(f"SELECT * FROM tasks WHERE {where} ORDER BY {order}", args)]

    def release_expired(self, now: datetime) -> int:
        """A worker that died leaves 'running' rows behind; give them back to the queue."""
        cur = self.conn.execute("UPDATE tasks SET status='pending', lease_owner=NULL, lease_until=NULL WHERE status='running' AND lease_until < ?", (iso(now),))
        return cur.rowcount

    def claim(self, owner: str, now: datetime, lease_seconds: int = 1800, respect_cycle: bool = True, kinds: list[str] | None = None) -> dict | None:
        """Atomically take the next runnable task: pending, past its times, and every dependency satisfied.

        A dependency written ``~key`` is soft: it only has to be finished one way or another.
        """
        with self.tx():
            sql = "SELECT * FROM tasks WHERE status='pending' AND (not_before IS NULL OR not_before <= ?)"
            args: list = [iso(now)]
            if respect_cycle:
                sql += " AND (cycle_at IS NULL OR cycle_at <= ?)"
                args.append(iso(now))
            if kinds:
                sql += f" AND kind IN ({','.join('?' * len(kinds))})"
                args += kinds
            rows = self.q(sql + " ORDER BY priority, COALESCE(cycle_at, created_at), id", tuple(args))
            if not rows:
                return None
            state = {r["key"]: r["status"] for r in self.q("SELECT key, status FROM tasks")}
            for row in rows:
                deps = _loads(row["depends_on"], [])
                ok = True
                for d in deps:
                    soft = d.startswith("~")
                    st = state.get(d.lstrip("~"))
                    if st is None:
                        continue                       # a dependency that was never planned cannot block
                    if soft and st in TERMINAL + ("blocked",):
                        continue
                    if st != "done":
                        ok = False
                        break
                if not ok:
                    continue
                self.conn.execute("UPDATE tasks SET status='running', attempts=attempts+1, lease_owner=?, lease_until=?, started_at=? WHERE id=?",
                                  (owner, iso(now + timedelta(seconds=lease_seconds)), iso(now), row["id"]))
                return self._task(self.one("SELECT * FROM tasks WHERE id=?", (row["id"],)))
        return None

    def finish_task(self, task_id: int, result: dict, now: datetime) -> None:
        self.conn.execute("UPDATE tasks SET status='done', result=?, error=NULL, error_class=NULL, lease_owner=NULL, lease_until=NULL, finished_at=? WHERE id=?",
                          (json.dumps(result, default=str), iso(now), task_id))

    def retry_task(self, task_id: int, error_class: str, error: str, at: datetime, uncount: bool = False) -> None:
        self.conn.execute("UPDATE tasks SET status='pending', error_class=?, error=?, not_before=?, lease_owner=NULL, lease_until=NULL, "
                          "attempts=attempts-? WHERE id=?", (error_class, error[:2000], iso(at), 1 if uncount else 0, task_id))

    def block_task(self, task_id: int, error: str, recheck_at: datetime) -> None:
        self.conn.execute("UPDATE tasks SET status='blocked', error_class='blocked', error=?, not_before=?, lease_owner=NULL, lease_until=NULL, attempts=attempts-1 WHERE id=?",
                          (error[:2000], iso(recheck_at), task_id))

    def fail_task(self, task_id: int, error_class: str, error: str, now: datetime) -> None:
        self.conn.execute("UPDATE tasks SET status='failed', error_class=?, error=?, lease_owner=NULL, lease_until=NULL, finished_at=? WHERE id=?",
                          (error_class, error[:2000], iso(now), task_id))

    def unblock_due(self, now: datetime) -> int:
        cur = self.conn.execute("UPDATE tasks SET status='pending' WHERE status='blocked' AND (not_before IS NULL OR not_before <= ?)", (iso(now),))
        return cur.rowcount

    def cancel_downstream(self, key: str, now: datetime, reason: str) -> list[str]:
        """Cancel every not-yet-finished task that (transitively) hard-depends on ``key``."""
        cancelled, frontier = [], {key}
        rows = self.q("SELECT id, key, status, depends_on FROM tasks WHERE status IN ('pending','blocked')")
        changed = True
        while changed:
            changed = False
            for r in rows:
                if r["key"] in cancelled:
                    continue
                if any(d in frontier for d in _loads(r["depends_on"], []) if not d.startswith("~")):
                    self.conn.execute("UPDATE tasks SET status='cancelled', error=?, finished_at=? WHERE id=?", (reason[:500], iso(now), r["id"]))
                    cancelled.append(r["key"])
                    frontier.add(r["key"])
                    changed = True
        return cancelled

    # ------------------------------------------------------------------ reports, ledgers
    def add_report(self, report: dict, now: datetime, task_key: str | None = None, episode_id: str | None = None, seconds: float | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO reports(ts,agent,task_id,task_key,episode_id,status,output,evidence,errors,next_action,seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (iso(now), report["agent"], str(report["task_id"]), task_key, episode_id, report["status"], json.dumps(report["output"], default=str),
             json.dumps(report["evidence"], default=str), json.dumps(report["errors"], default=str), report["next_action"], seconds))
        return cur.lastrowid

    def reports(self, where: str = "1=1", args: tuple = (), limit: int = 200) -> list[dict]:
        rows = self.q(f"SELECT * FROM reports WHERE {where} ORDER BY id DESC LIMIT ?", (*args, limit))
        for r in rows:
            for k in ("output", "evidence", "errors"):
                r[k] = _loads(r[k], {} if k == "output" else [])
        return rows

    def add_licences(self, episode_id: str, rows: list[dict], now: datetime) -> None:
        self.conn.execute("DELETE FROM licences WHERE episode_id=?", (episode_id,))
        self.conn.executemany("INSERT INTO licences(episode_id,kind,name,origin,license,evidence,created_at) VALUES(?,?,?,?,?,?,?)",
                              [(episode_id, r["kind"], r["name"], r["origin"], r["license"], r.get("evidence"), iso(now)) for r in rows])

    def add_cost(self, now: datetime, day: str, category: str, provider: str, usd: float, units: float = 0, unit: str = "", episode_id: str | None = None,
                 estimated: bool = False, note: str = "") -> None:
        self.conn.execute("INSERT INTO costs(ts,day,episode_id,category,provider,units,unit,usd,estimated,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (iso(now), day, episode_id, category, provider, units, unit, usd, int(estimated), note))

    def spend(self, since_day: str, until_day: str | None = None) -> float:
        return float(self.scalar("SELECT COALESCE(SUM(usd),0) FROM costs WHERE day >= ? AND day <= ?", (since_day, until_day or "9999-12-31")))

    def add_document(self, kind: str, period: str, title: str, body: str, data: dict, now: datetime) -> None:
        self.conn.execute("INSERT INTO documents(ts,kind,period,title,body,data) VALUES(?,?,?,?,?,?) ON CONFLICT(kind,period) DO UPDATE SET "
                          "ts=excluded.ts, title=excluded.title, body=excluded.body, data=excluded.data",
                          (iso(now), kind, period, title, body, json.dumps(data, default=str)))

    def notify(self, level: str, title: str, body: str, now: datetime, fingerprint: str | None = None) -> int | None:
        """Queue a notification; the same fingerprint is not repeated within a day."""
        if fingerprint:
            dup = self.scalar("SELECT id FROM notifications WHERE fingerprint=? AND ts >= ?", (fingerprint, iso(now - timedelta(hours=24))))
            if dup:
                return None
        cur = self.conn.execute("INSERT INTO notifications(ts,level,title,body,fingerprint) VALUES(?,?,?,?,?)", (iso(now), level, title, body, fingerprint))
        return cur.lastrowid
