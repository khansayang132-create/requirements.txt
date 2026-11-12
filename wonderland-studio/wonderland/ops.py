"""Operations: health checks, backups, notifications and the owner's reports.

Reports are built only from database rows (episodes, tasks, reports, costs, analytics). When
something is unknown — no analytics yet, YouTube not connected — the report says that in
words instead of showing a zero.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

from . import finance
from .db import iso
from .protocol import AgentReport

KEEP_BACKUPS = 14


# ------------------------------------------------------------------ health
def health(studio) -> dict:
    checks = []

    def check(name: str, ok: bool, detail: str, level: str = "error") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "level": level if not ok else "ok"})

    du = shutil.disk_usage(studio.state)
    check("disk_space", du.free > 2 * 1024**3, f"{du.free / 1024**3:.1f} GB free")
    check("ffmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "not installed")
    try:
        rows = studio.desk.doctor()
        ok = [r["provider"] for r in rows if r["available"]]
        check("voice", bool(ok), "available: " + (", ".join(ok) or "none"))
        check("voice_quality", "kokoro" in ok or "elevenlabs" in ok, "neural voice available" if ("kokoro" in ok or "elevenlabs" in ok)
              else "only the robotic fallback voice is available: python -m wonderland voices install", level="warning")
    except Exception as e:  # noqa: BLE001
        check("voice", False, str(e))
    integrity = studio.db.scalar("PRAGMA integrity_check")
    check("database", integrity == "ok", integrity)
    stuck = studio.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='running' AND lease_until < ?", (iso(studio.now()),))
    check("no_stuck_tasks", not stuck, f"{stuck} expired lease(s)", level="warning")
    failed = studio.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='failed' AND finished_at >= ?", (iso(studio.now() - timedelta(days=1)),))
    check("failures_24h", failed == 0, f"{failed} failed task(s) in 24 h", level="warning")
    blocked = studio.db.q("SELECT key, error FROM tasks WHERE status='blocked' LIMIT 5")
    check("nothing_blocked", not blocked, "; ".join(f"{b['key']}: {(b['error'] or '')[:80]}" for b in blocked) or "none", level="warning")
    upcoming = studio.db.scalar("SELECT COUNT(*) FROM episodes WHERE status IN ('produced','uploaded','scheduled') AND publish_at > ?", (iso(studio.now()),))
    check("production_buffer", upcoming >= len(studio.slots()), f"{upcoming} finished episode(s) waiting for their slot", level="warning")
    lim = finance.limits(studio)
    sp = finance.spent(studio)
    check("budget", sp["today_usd"] <= lim["daily_usd_limit"] + 1e-9 and sp["month_usd"] <= lim["monthly_usd_limit"] + 1e-9,
          f"today ${sp['today_usd']:.4f} / ${lim['daily_usd_limit']:.2f}, month ${sp['month_usd']:.4f} / ${lim['monthly_usd_limit']:.2f}")
    status = "ok" if all(c["ok"] or c["level"] == "warning" for c in checks) else "degraded"
    if status == "ok" and any(not c["ok"] for c in checks):
        status = "warnings"
    return {"status": status, "checks": checks, "at": iso(studio.now())}


def handle_health(studio, task: dict, ep: dict | None) -> AgentReport:
    h = health(studio)
    studio.db.set("health", h, studio.now())
    bad = [c for c in h["checks"] if not c["ok"] and c["level"] == "error"]
    if bad:
        studio.notify("error", "Health check failed", "\n".join(f"{c['name']}: {c['detail']}" for c in bad), fingerprint="health:" + ",".join(c["name"] for c in bad))
    deliver(studio)
    return AgentReport("infrastructure", task["key"], "success", output={"status": h["status"], "problems": [c["name"] for c in h["checks"] if not c["ok"]]},
                       evidence=[{c["name"]: c["detail"]} for c in h["checks"]], next_action="none" if not bad else "owner looks at the failed checks")


# ------------------------------------------------------------------ backup
def backup(studio) -> Path:
    folder = studio.state / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"wonderland-{studio.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(str(dest)) as out:
        studio.db.conn.backup(out)
    with sqlite3.connect(str(dest)) as chk:
        if chk.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"backup {dest} failed its integrity check")
    for old in sorted(folder.glob("wonderland-*.db"))[:-KEEP_BACKUPS]:
        old.unlink()
    return dest


def handle_backup(studio, task: dict, ep: dict | None) -> AgentReport:
    dest = backup(studio)
    return AgentReport("infrastructure", task["key"], "success", output={"backup": str(dest), "bytes": dest.stat().st_size},
                       evidence=[str(dest), {"integrity_check": "ok"}], next_action="none")


# ------------------------------------------------------------------ notifications
def deliver(studio) -> dict:
    """Send queued notifications to Telegram when configured; otherwise they stay in the database (dashboard + status)."""
    token, chat = os.environ.get("WONDERLAND_TELEGRAM_TOKEN"), os.environ.get("WONDERLAND_TELEGRAM_CHAT")
    rows = studio.db.q("SELECT * FROM notifications WHERE delivered=0 ORDER BY id LIMIT 20")
    if not (token and chat and studio.cfg.get("notifications", {}).get("telegram", True)):
        return {"sent": 0, "queued": len(rows), "channel": "database only (Telegram not configured)"}
    sent = 0
    for n in rows:
        data = urllib.parse.urlencode({"chat_id": chat, "text": f"[{n['level']}] {n['title']}\n{n['body']}"[:3900]}).encode()
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=15) as r:
                ok = r.status == 200
        except Exception as e:  # noqa: BLE001 - delivery failure is recorded, never fatal
            studio.db.conn.execute("UPDATE notifications SET error=? WHERE id=?", (type(e).__name__, n["id"]))
            continue
        if ok:
            studio.db.conn.execute("UPDATE notifications SET delivered=1, channel='telegram' WHERE id=?", (n["id"],))
            sent += 1
    return {"sent": sent, "queued": len(rows) - sent, "channel": "telegram"}


# ------------------------------------------------------------------ reports
def build_report(studio, kind: str = "daily") -> dict:
    from .departments.analytics import UNAVAILABLE, per_video

    days = {"daily": 1, "weekly": 7, "monthly": 30}[kind]
    end = studio.local_day()
    start = end - timedelta(days=days - 1)
    s, e = f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}"
    eps = studio.db.episodes("day >= ? AND day <= ?", (s, e))
    by_status: dict[str, int] = {}
    for ep in eps:
        by_status[ep["status"]] = by_status.get(ep["status"], 0) + 1
    published = [ep for ep in eps if ep["status"] == "published"]
    perf = []
    for ep in published:
        pv = per_video(studio.db, ep["video_id"])
        perf.append({"episode": ep["id"], "title": ep["title"], "video": f"https://youtu.be/{ep['video_id']}",
                     **({k: round(v, 2) for k, v in pv.items()} if pv.get("days_with_data") else {"metrics": "no data yet"})})
    tasks = studio.db.q("SELECT status, COUNT(*) AS n FROM tasks WHERE created_at >= ? GROUP BY status", (f"{s}T00:00:00Z",))
    failures = studio.db.q("SELECT key, error_class, error FROM tasks WHERE status='failed' AND finished_at >= ? ORDER BY finished_at DESC LIMIT 10",
                           (f"{s}T00:00:00Z",))
    blocked = studio.db.q("SELECT key, error FROM tasks WHERE status='blocked'")
    channel = studio.db.q("SELECT metric, value, day FROM channel_stats WHERE day=(SELECT MAX(day) FROM channel_stats)")
    data = {
        "kind": kind, "from": s, "to": e, "episodes": len(eps), "by_status": by_status, "published": len(published), "performance": perf,
        "channel": {r["metric"]: r["value"] for r in channel} or "YouTube not connected or no data yet",
        "tasks": {r["status"]: r["n"] for r in tasks}, "failures": failures, "blocked": blocked,
        "costs": finance.summary(studio, days), "health": (studio.db.get("health") or {}).get("status", "not checked yet"),
        "not_available": UNAVAILABLE, "publishing_mode": studio.publish_mode,
    }
    lines = [f"# Wonderland {kind} report {s}{'' if s == e else ' → ' + e}", "",
             f"Episodes: {len(eps)} — " + (", ".join(f"{k} {v}" for k, v in sorted(by_status.items())) or "none"),
             f"Published and verified on YouTube: {len(published)}", f"Publishing mode: {studio.publish_mode}",
             f"Health: {data['health']}", ""]
    if perf:
        lines += ["## Performance (YouTube Analytics)", *[f"- {p['title']}: " + (", ".join(f"{k} {v}" for k, v in p.items() if k not in ("episode", "title", "video"))) for p in perf], ""]
    else:
        lines += ["## Performance", "No published videos with analytics in this period. Nothing is estimated.", ""]
    if blocked:
        lines += ["## Needs you", *[f"- {b['key']}: {b['error']}" for b in blocked], ""]
    if failures:
        lines += ["## Failures", *[f"- {f['key']} ({f['error_class']}): {(f['error'] or '')[:160]}" for f in failures], ""]
    c = data["costs"]
    lines += ["## Costs", f"Real spend this month: ${c['spent']['month_usd']:.4f} (limit ${c['limits']['monthly_usd_limit']:.2f}); "
              f"compute time {c['spent']['month_compute_seconds'] / 60:.1f} min.", "",
              "Not in the API, so never shown: " + ", ".join(UNAVAILABLE)]
    return {"title": lines[0][2:], "body": "\n".join(lines), "data": data}


def handle_report(studio, task: dict, ep: dict | None) -> AgentReport:
    today = studio.local_day()
    made = []
    kinds = ["daily"] + (["weekly"] if today.weekday() == 6 else []) + (["monthly"] if (today + timedelta(days=1)).day == 1 else [])
    for kind in kinds:
        r = build_report(studio, kind)
        studio.db.add_document(kind, f"{today:%Y-%m-%d}", r["title"], r["body"], r["data"], studio.now())
        made.append(kind)
    out_dir = studio.state / "reports"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"daily-{today:%Y-%m-%d}.md"
    path.write_text(build_report(studio, "daily")["body"], encoding="utf-8")
    blocked = studio.db.scalar("SELECT COUNT(*) FROM tasks WHERE status='blocked'")
    if blocked:
        studio.notify("action", f"{blocked} task(s) need you", "Run: python -m wonderland status", fingerprint=f"daily-blocked:{today}")
    return AgentReport("reporting", task["key"], "success", output={"reports": made, "file": str(path)}, evidence=[str(path)], next_action="none")


def json_default(o):
    return str(o)


def dumps(o) -> str:
    return json.dumps(o, indent=2, ensure_ascii=False, default=json_default)
