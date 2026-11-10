#!/usr/bin/env python3
"""Query the official YouTube Analytics API (v2, reports.query) for the authenticated channel.

Reports:
  overview   views, watch time, avg view duration/percentage, subscribers gained/lost, likes, comments, shares
  daily      the overview metrics per day
  traffic    views + watch time by traffic source (insightTrafficSourceType)
  retention  audienceWatchRatio + relativeRetentionPerformance by elapsedVideoTimeRatio (needs --video-id)
  custom     your own --metrics / --dimensions

Honesty rules:
* A metric YouTube did not return is reported as "unavailable", never as 0.
* An empty result is reported as "no_data" (e.g. no views in range, or data not processed yet:
  Analytics data usually lags 1-3 days).
* Impressions and impressions click-through rate are NOT exposed by the Analytics API
  (verified against the official metrics reference, last updated 2026-09-14). They are
  listed as unavailable with a pointer to YouTube Studio → Analytics → Reach.

Examples:
  python skills/youtube-analytics/scripts/analytics.py --report overview --days 28
  python skills/youtube-analytics/scripts/analytics.py --report daily --start 2026-10-01 --end 2026-10-31 --out state/reports/oct.json
  python skills/youtube-analytics/scripts/analytics.py --report retention --video-id VIDEO_ID --days 90
  python skills/youtube-analytics/scripts/analytics.py --report custom --metrics views,likes --dimensions country --sort -views --max-results 10
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src import cli  # noqa: E402
from src.exceptions import ValidationError  # noqa: E402

OVERVIEW = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "subscribersGained", "subscribersLost", "likes", "comments", "shares"]

REPORTS = {
    "overview": {"metrics": OVERVIEW, "dimensions": None, "sort": None},
    "daily": {"metrics": OVERVIEW, "dimensions": "day", "sort": "day"},
    "traffic": {"metrics": ["views", "estimatedMinutesWatched"], "dimensions": "insightTrafficSourceType", "sort": "-views"},
    "retention": {"metrics": ["audienceWatchRatio", "relativeRetentionPerformance"], "dimensions": "elapsedVideoTimeRatio", "sort": "elapsedVideoTimeRatio"},
}

NOT_IN_API = {
    "impressions": "Thumbnail impressions are not exposed by the YouTube Analytics API; see YouTube Studio → Analytics → Reach.",
    "impressionsClickThroughRate": "Impressions click-through rate is not exposed by the YouTube Analytics API; see YouTube Studio → Analytics → Reach.",
}


def build_query(report: str, *, start: str, end: str, video_id: str | None, metrics: list[str] | None, dimensions: str | None,
                sort: str | None, max_results: int | None) -> tuple[dict, dict]:
    if report == "custom":
        if not metrics:
            raise ValidationError("--report custom needs --metrics")
        spec = {"metrics": metrics, "dimensions": dimensions, "sort": sort}
    else:
        spec = dict(REPORTS[report])
    if report == "retention" and not video_id:
        raise ValidationError("The retention report needs --video-id (YouTube only returns retention for a single video).")
    requested = list(spec["metrics"])
    unavailable = {m: NOT_IN_API[m] for m in requested if m in NOT_IN_API}
    api_metrics = [m for m in requested if m not in NOT_IN_API]
    if report == "overview":
        unavailable.update(NOT_IN_API)
    if not api_metrics:
        raise ValidationError("None of the requested metrics are available from the Analytics API", list(unavailable.values()))
    params = {
        "ids": "channel==MINE",
        "startDate": start,
        "endDate": end,
        "metrics": ",".join(api_metrics),
        "dimensions": spec.get("dimensions"),
        "sort": sort or spec.get("sort"),
        "filters": f"video=={video_id}" if video_id else None,
        "maxResults": max_results,
    }
    return params, unavailable


def normalize(response: dict, params: dict, unavailable: dict) -> dict:
    headers = [h.get("name") for h in response.get("columnHeaders", [])]
    rows = response.get("rows") or []
    requested = params["metrics"].split(",")
    out: dict = {
        "query": {k: v for k, v in params.items() if v is not None},
        "columns": headers,
        "rows": rows,
        "row_count": len(rows),
        "status": "ok" if rows else "no_data",
        "metrics": {},
    }
    if not params.get("dimensions") and rows:
        values = dict(zip(headers, rows[0], strict=False))
        for m in requested:
            out["metrics"][m] = {"value": values[m], "status": "ok"} if m in values else {"value": None, "status": "unavailable", "reason": "not returned by the API for this query"}
    else:
        for m in requested:
            if m not in headers:
                out["metrics"][m] = {"value": None, "status": "unavailable", "reason": "not returned by the API for this query"}
            elif not rows:
                out["metrics"][m] = {"value": None, "status": "no_data"}
            else:
                out["metrics"][m] = {"value": None, "status": "per_row"}
    for m, reason in unavailable.items():
        out["metrics"][m] = {"value": None, "status": "unavailable", "reason": reason}
    if not rows:
        out["note"] = "No rows returned: no activity in this range, or YouTube has not processed it yet (usually 1-3 days behind)."
    return out


def date_range(args: argparse.Namespace) -> tuple[str, str]:
    if args.start:
        start, end = args.start, args.end or date.today().isoformat()
    else:
        end_d = date.today()
        start, end = (end_d - timedelta(days=args.days - 1)).isoformat(), end_d.isoformat()
    try:
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValidationError(f"start {start} is after end {end}")
    except ValueError as exc:
        raise ValidationError(f"Dates must be YYYY-MM-DD: {exc}") from exc
    return start, end


def run_report(client, report: str, start: str, end: str, **kw) -> dict:
    params, unavailable = build_query(report, start=start, end=end, **kw)
    response = client.analytics_query(**params)
    result = normalize(response, params, unavailable)
    result["report"] = report
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--report", choices=[*REPORTS, "custom"], default="overview")
    p.add_argument("--days", type=int, default=28, help="Last N days ending today (ignored if --start)")
    p.add_argument("--start", help="YYYY-MM-DD")
    p.add_argument("--end", help="YYYY-MM-DD (default today)")
    p.add_argument("--video-id", help="Restrict to one video")
    p.add_argument("--metrics", help="custom: comma-separated metric names")
    p.add_argument("--dimensions", help="custom: comma-separated dimension names")
    p.add_argument("--sort")
    p.add_argument("--max-results", type=int)
    p.add_argument("--out", help="Save the result JSON (input for reports.py)")
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()
    start, end = date_range(args)
    client = cli.make_client(rt, ["analytics.reports.query"])
    result = run_report(client, args.report, start, end, video_id=args.video_id,
                        metrics=args.metrics.split(",") if args.metrics else None, dimensions=args.dimensions,
                        sort=args.sort, max_results=args.max_results)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {args.out}", file=sys.stderr)
    from reports import render_markdown  # same folder

    cli.emit(result, args.json, render_markdown)
    return 0


if __name__ == "__main__":
    cli.run(main)
