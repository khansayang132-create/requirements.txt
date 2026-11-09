#!/usr/bin/env python3
"""Explain how the toolkit treats an API error: classification, whether it is retried,
the backoff schedule from settings.yaml, and what to do next. Local only.

The retry engine itself is src/retry.py (used by every API call).

Examples:
  python skills/youtube-pipeline/scripts/retry_manager.py --status 503
  python skills/youtube-pipeline/scripts/retry_manager.py --status 403 --reason quotaExceeded
  python skills/youtube-pipeline/scripts/retry_manager.py --policy
  python skills/youtube-pipeline/scripts/retry_manager.py --from-log logs/ytaos.jsonl --last 20
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import cli  # noqa: E402
from src.retry import HINTS, RETRYABLE, classify  # noqa: E402


def explain(status: int | None, reason: str | None, policy) -> dict:
    cls = classify(status, reason)
    return {
        "http_status": status,
        "reason": reason,
        "classification": cls.value,
        "retried": cls in RETRYABLE,
        "max_attempts": policy.max_attempts if cls in RETRYABLE else 1,
        "backoff_upper_bounds_s": policy.schedule() if cls in RETRYABLE else [],
        "hint": HINTS[cls],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--status", type=int, help="HTTP status (omit for a network error/timeout)")
    p.add_argument("--reason", help="Google error reason, e.g. quotaExceeded, rateLimitExceeded, backendError")
    p.add_argument("--policy", action="store_true", help="Show the configured retry policy")
    p.add_argument("--from-log", help="Explain the failed calls in a ytaos.jsonl log")
    p.add_argument("--last", type=int, default=20)
    cli.add_output_flags(p)
    args = p.parse_args()
    rt = cli.runtime()
    policy = rt.policy

    if args.policy:
        cli.emit({"max_attempts": policy.max_attempts, "base_delay_s": policy.base_delay, "max_delay_s": policy.max_delay,
                  "jitter": "full (uniform 0..bound)", "backoff_upper_bounds_s": policy.schedule()}, True)
        return 0
    if args.from_log:
        rows = []
        for line in Path(args.from_log).read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("error_class"):
                rows.append({"at": rec.get("timestamp"), "request_id": rec.get("request_id"), "operation": rec.get("operation"),
                             "http_status": rec.get("http_status"), "error_class": rec.get("error_class"),
                             "retry_count": rec.get("retry_count"), "result": rec.get("result")})
        cli.emit(rows[-args.last:], True)
        return 0
    cli.emit(explain(args.status, args.reason, policy), args.json, lambda d: (
        f"HTTP {d['http_status']} {d['reason'] or ''} → {d['classification']}; "
        + (f"retried up to {d['max_attempts']} attempts, waits ≤ {d['backoff_upper_bounds_s']} s" if d["retried"] else "not retried")
        + f"\n{d['hint']}"))
    return 0


if __name__ == "__main__":
    cli.run(main)
