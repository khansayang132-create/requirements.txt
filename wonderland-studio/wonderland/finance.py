"""Finance: what the studio spends, and the limits it may not cross.

The default pipeline costs nothing per video (free voice, in-house music, local rendering).
Money can only leave through a paid provider, and that needs BOTH switches in ``studio.yaml``:
``budget.paid_providers_authorized: true`` and limits above zero. Compute is recorded as an
estimate (runner minutes × the configured rate) and marked as such.
"""

from __future__ import annotations

from datetime import timedelta

from .protocol import BlockedError


def limits(studio) -> dict:
    b = studio.cfg.get("budget", {})
    return {"paid_providers_authorized": bool(b.get("paid_providers_authorized", False)),
            "daily_usd_limit": float(b.get("daily_usd_limit", 0) or 0), "monthly_usd_limit": float(b.get("monthly_usd_limit", 0) or 0)}


def spent(studio) -> dict:
    today = studio.local_day()
    month_start = today.replace(day=1)
    real = "estimated=0"
    q = studio.db.scalar
    return {
        "today_usd": float(q(f"SELECT COALESCE(SUM(usd),0) FROM costs WHERE day=? AND {real}", (f"{today:%Y-%m-%d}",))),
        "month_usd": float(q(f"SELECT COALESCE(SUM(usd),0) FROM costs WHERE day>=? AND {real}", (f"{month_start:%Y-%m-%d}",))),
        "month_estimated_compute_usd": float(q("SELECT COALESCE(SUM(usd),0) FROM costs WHERE day>=? AND estimated=1", (f"{month_start:%Y-%m-%d}",))),
        "month_compute_seconds": float(q("SELECT COALESCE(SUM(units),0) FROM costs WHERE day>=? AND category='compute'", (f"{month_start:%Y-%m-%d}",))),
    }


def require_budget(studio, usd: float, what: str) -> None:
    """Raise BlockedError unless spending ``usd`` now is authorized and inside both limits."""
    lim, sp = limits(studio), spent(studio)
    if not lim["paid_providers_authorized"]:
        raise BlockedError(f"{what} costs about ${usd:.4f} and paid providers are not authorized",
                           needs="owner sets budget.paid_providers_authorized: true in config/studio.yaml (or keeps the free voice)")
    if sp["today_usd"] + usd > lim["daily_usd_limit"]:
        raise BlockedError(f"{what} (${usd:.4f}) would pass today's limit of ${lim['daily_usd_limit']:.2f} (spent ${sp['today_usd']:.4f})",
                           needs="owner raises budget.daily_usd_limit or waits until tomorrow")
    if sp["month_usd"] + usd > lim["monthly_usd_limit"]:
        raise BlockedError(f"{what} (${usd:.4f}) would pass this month's limit of ${lim['monthly_usd_limit']:.2f} (spent ${sp['month_usd']:.4f})",
                           needs="owner raises budget.monthly_usd_limit")


def record_compute(studio, task: dict, seconds: float) -> None:
    if seconds < 0.5:
        return
    rate = float(studio.cfg.get("budget", {}).get("runner_usd_per_minute", 0) or 0)
    day = f"{studio.local_day():%Y-%m-%d}"
    studio.db.add_cost(studio.now(), day, "compute", "runner", round(seconds / 60 * rate, 6), units=round(seconds, 2), unit="s",
                       episode_id=task.get("episode_id"), estimated=True, note=task["kind"])


def summary(studio, days: int = 30) -> dict:
    since = f"{studio.local_day() - timedelta(days=days):%Y-%m-%d}"
    rows = studio.db.q("SELECT category, provider, estimated, ROUND(SUM(usd),6) AS usd, ROUND(SUM(units),1) AS units, unit, COUNT(*) AS entries "
                       "FROM costs WHERE day>=? GROUP BY category, provider, estimated, unit ORDER BY usd DESC", (since,))
    produced = studio.db.scalar("SELECT COUNT(*) FROM episodes WHERE video_path IS NOT NULL AND day>=?", (since,)) or 0
    total_real = sum(r["usd"] for r in rows if not r["estimated"])
    total_est = sum(r["usd"] for r in rows if r["estimated"])
    return {"window_days": days, "limits": limits(studio), "spent": spent(studio), "by_category": rows, "videos_produced": produced,
            "usd_per_video_real": round(total_real / produced, 6) if produced else None,
            "usd_per_video_including_estimated_compute": round((total_real + total_est) / produced, 6) if produced else None,
            "note": "real = billed by a provider; estimated = runner time × budget.runner_usd_per_minute"}
