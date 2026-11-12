"""Analytics department: real numbers from YouTube, nothing else.

Pulls per-video metrics from the YouTube Analytics API (views, minutes watched, average view
percentage, subscribers gained) and public counters from the Data API. Every row is stored
with the time it was fetched. When YouTube is not connected or a video has no data yet, the
report says so; no number is ever estimated or filled in.

Not available through the API (and therefore never shown): impressions, impressions CTR and
"returning viewers".
"""

from __future__ import annotations

from datetime import timedelta

from ..db import iso
from ..protocol import AgentReport, BlockedError

METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "subscribersGained"]
UNAVAILABLE = ["impressions", "impressionsClickThroughRate", "returningViewers"]


def fetch(studio, client, videos: list[dict], start: str, end: str) -> dict:
    now = iso(studio.now())
    stored, empty = 0, []
    for ep in videos:
        resp = client.analytics_query(ids="channel==MINE", startDate=start, endDate=end, metrics=",".join(METRICS),
                                      dimensions="day", filters=f"video=={ep['video_id']}")
        headers = [h["name"] for h in resp.get("columnHeaders", [])]
        rows = resp.get("rows") or []
        if not rows:
            empty.append(ep["video_id"])
        for row in rows:
            rec = dict(zip(headers, row))
            for m in METRICS:
                if m in rec and rec[m] is not None:
                    studio.db.conn.execute("INSERT INTO analytics(video_id,day,metric,value,fetched_at) VALUES(?,?,?,?,?) "
                                           "ON CONFLICT(video_id,day,metric) DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at",
                                           (ep["video_id"], rec["day"], m, float(rec[m]), now))
                    stored += 1
    return {"rows_stored": stored, "videos_without_data_yet": empty}


def channel_counters(studio, client) -> dict:
    ch = client.channel_statistics() if hasattr(client, "channel_statistics") else None
    if not ch:
        return {}
    stats = ch.get("statistics", {})
    day = f"{studio.local_day():%Y-%m-%d}"
    out = {}
    for k in ("subscriberCount", "viewCount", "videoCount"):
        if stats.get(k) is not None and not (k == "subscriberCount" and stats.get("hiddenSubscriberCount")):
            out[k] = float(stats[k])
            studio.db.conn.execute("INSERT INTO channel_stats(day,metric,value,fetched_at) VALUES(?,?,?,?) ON CONFLICT(day,metric) DO UPDATE SET "
                                   "value=excluded.value, fetched_at=excluded.fetched_at", (day, k, out[k], iso(studio.now())))
    return out


def per_video(db, video_id: str) -> dict:
    rows = db.q("SELECT metric, SUM(value) AS total, AVG(value) AS mean, COUNT(*) AS days FROM analytics WHERE video_id=? GROUP BY metric", (video_id,))
    out = {r["metric"]: (r["mean"] if r["metric"] in ("averageViewPercentage", "averageViewDuration") else r["total"]) for r in rows}
    out["days_with_data"] = max((r["days"] for r in rows), default=0)
    return out


def handle_analytics(studio, task: dict, ep: dict | None) -> AgentReport:
    from .publishing import make_client

    videos = studio.db.q("SELECT id, video_id, format, category FROM episodes WHERE status='published' AND video_id IS NOT NULL")
    if not videos:
        return AgentReport("analytics", task["key"], "skipped", errors=["no published videos yet"], next_action="nothing to measure until a video is public")
    try:
        client, _ = make_client(studio, ["analytics.reports.query", "channels.list"])
    except BlockedError as e:
        return AgentReport("analytics", task["key"], "skipped", errors=[str(e)], next_action=e.needs)
    today = studio.local_day()
    start = f"{today - timedelta(days=28):%Y-%m-%d}"
    res = fetch(studio, client, videos, start, f"{today:%Y-%m-%d}")
    counters = channel_counters(studio, client)
    return AgentReport("analytics", task["key"], "success",
                       output={**res, "videos": len(videos), "window": [start, f"{today:%Y-%m-%d}"], "channel": counters, "unavailable_in_api": UNAVAILABLE},
                       evidence=[{"source": "youtubeAnalytics.reports.query"}, {"rows": res["rows_stored"]}], next_action="improve")
