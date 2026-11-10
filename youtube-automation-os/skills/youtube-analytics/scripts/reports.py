#!/usr/bin/env python3
"""Render analytics results as a Markdown report, optionally comparing two periods.

Offline mode renders JSON saved by analytics.py --out. Live mode (--live) fetches the
current period and the equal-length period before it, then shows the change.
Unavailable metrics stay "unavailable" (never 0); periods with no data say so.

Examples:
  python skills/youtube-analytics/scripts/reports.py --input state/reports/oct.json
  python skills/youtube-analytics/scripts/reports.py --input this.json --compare last.json --out state/reports/report.md
  python skills/youtube-analytics/scripts/reports.py --live --days 28 --video-id VIDEO_ID
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import cli  # noqa: E402

LABELS = {
    "views": "Views",
    "estimatedMinutesWatched": "Watch time (minutes, estimated)",
    "averageViewDuration": "Average view duration (s)",
    "averageViewPercentage": "Average view percentage (%)",
    "subscribersGained": "Subscribers gained",
    "subscribersLost": "Subscribers lost",
    "likes": "Likes",
    "comments": "Comments",
    "shares": "Shares",
    "impressions": "Impressions",
    "impressionsClickThroughRate": "Impressions CTR",
}


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _value(entry: dict) -> str:
    status = entry.get("status")
    if status == "ok":
        return _fmt(entry.get("value"))
    if status == "unavailable":
        return "unavailable"
    if status == "no_data":
        return "no data"
    return "see table"


def delta(cur, prev) -> str:
    if not isinstance(cur, (int, float)) or not isinstance(prev, (int, float)):
        return "n/a"
    diff = cur - prev
    pct = f" ({diff / prev:+.1%})" if prev else ""
    return f"{diff:+,.2f}{pct}" if isinstance(diff, float) else f"{diff:+,}{pct}"


def render_markdown(result: dict, previous: dict | None = None) -> str:
    q = result.get("query", {})
    lines = [f"# YouTube Analytics — {result.get('report', 'report')}", "",
             f"Period: {q.get('startDate')} → {q.get('endDate')}" + (f" · filter {q['filters']}" if q.get("filters") else ""), ""]
    if previous:
        pq = previous.get("query", {})
        lines.append(f"Compared with: {pq.get('startDate')} → {pq.get('endDate')}")
        lines.append("")
    if result.get("note"):
        lines += [f"> {result['note']}", ""]
    metrics = result.get("metrics", {})
    if q.get("dimensions"):
        cols = result.get("columns", [])
        lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for row in result.get("rows", [])[:200]:
            lines.append("| " + " | ".join(_fmt(c) for c in row) + " |")
        if not result.get("rows"):
            lines.append("| " + " | ".join("no data" for _ in cols) + " |")
        lines.append("")
        extra = {k: v for k, v in metrics.items() if v.get("status") == "unavailable"}
    else:
        header = "| Metric | Value |" + (" Previous | Change |" if previous else "")
        lines += [header, "|---|---|" + ("---|---|" if previous else "")]
        for m, entry in metrics.items():
            row = f"| {LABELS.get(m, m)} | {_value(entry)} |"
            if previous:
                pe = previous.get("metrics", {}).get(m, {})
                row += f" {_value(pe)} | {delta(entry.get('value'), pe.get('value'))} |"
            lines.append(row)
        lines.append("")
        extra = {}
    unavailable = {k: v for k, v in metrics.items() if v.get("status") == "unavailable"} or extra
    if unavailable:
        lines.append("**Unavailable metrics (not zero — the API does not provide them here):**")
        for m, e in unavailable.items():
            lines.append(f"- {LABELS.get(m, m)}: {e.get('reason', '')}")
        lines.append("")
    lines.append("_Source: YouTube Analytics API v2 (reports.query). Figures are YouTube's estimates and may be revised._")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", help="Result JSON from analytics.py --out")
    p.add_argument("--compare", help="Earlier result JSON to compare against")
    p.add_argument("--live", action="store_true", help="Fetch this period and the previous one (overview report)")
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--video-id")
    p.add_argument("--out", help="Write the Markdown report here")
    cli.add_output_flags(p)
    args = p.parse_args()

    if args.live:
        from analytics import run_report

        rt = cli.runtime()
        client = cli.make_client(rt, ["analytics.reports.query"])
        end = date.today()
        start = end - timedelta(days=args.days - 1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=args.days - 1)
        current = run_report(client, "overview", start.isoformat(), end.isoformat(), video_id=args.video_id, metrics=None, dimensions=None, sort=None, max_results=None)
        previous = run_report(client, "overview", prev_start.isoformat(), prev_end.isoformat(), video_id=args.video_id, metrics=None, dimensions=None, sort=None, max_results=None)
    elif args.input:
        current = json.loads(Path(args.input).read_text(encoding="utf-8"))
        previous = json.loads(Path(args.compare).read_text(encoding="utf-8")) if args.compare else None
    else:
        p.error("give --input FILE or --live")

    md = render_markdown(current, previous)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md + "\n", encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    if args.json:
        cli.emit({"current": current, "previous": previous, "markdown": md}, True)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    cli.run(main)
