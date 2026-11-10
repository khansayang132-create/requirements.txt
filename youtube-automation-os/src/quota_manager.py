"""Quota estimation and accounting for the YouTube Data API v3 and Analytics API.

Costs live in ``config/settings.yaml`` under ``quota`` so they can be updated when Google
changes them. As verified on the official quota calculator (last updated 2026-11-03):

* the Data API project bucket defaults to 10,000 units/day for "all other endpoints";
* ``videos.insert`` and ``search.list`` each have their **own** bucket of 100 calls/day,
  1 unit per call (the old 1,600-unit upload cost no longer applies);
* ``thumbnails.set`` 50, ``videos.update`` 50, ``videos.delete`` 50, ``videos.list`` 1,
  ``captions.list`` 50, ``captions.insert`` 400, ``captions.update`` 450.

The ledger is an *estimate*: Google is the source of truth (Cloud Console → Quotas).
Quota resets at midnight Pacific Time, so the ledger is keyed by the Pacific date.
A ``403 quotaExceeded`` marks the bucket exhausted for the rest of that day; while it
is marked, ``check`` refuses new calls instead of retrying forever.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .exceptions import ConfigError, QuotaExceededError

try:
    from zoneinfo import ZoneInfo

    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - tz database missing (rare; e.g. minimal containers)
    _PACIFIC = timezone(timedelta(hours=-8), "PST")


def pacific_today(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(_PACIFIC).date().isoformat()


@dataclass
class Bucket:
    name: str
    daily_limit: int | None  # None = unknown/unlimited for our purposes
    unit: str = "units"  # "units" or "calls"


@dataclass
class QuotaEstimate:
    by_bucket: dict[str, int] = field(default_factory=dict)
    unknown_ops: list[str] = field(default_factory=list)
    unverified_ops: list[str] = field(default_factory=list)

    def total(self, bucket: str) -> int:
        return self.by_bucket.get(bucket, 0)


class QuotaManager:
    def __init__(self, quota_config: dict, ledger_path: Path | None, warn_ratio: float | None = None):
        if not isinstance(quota_config, dict) or "buckets" not in quota_config or "costs" not in quota_config:
            raise ConfigError("settings.yaml: 'quota' must define 'buckets' and 'costs'")
        self.buckets: dict[str, Bucket] = {}
        for name, spec in quota_config["buckets"].items():
            limit = spec.get("daily_limit")
            self.buckets[name] = Bucket(name, int(limit) if limit is not None else None, spec.get("unit", "units"))
        self.costs: dict[str, dict] = {}
        for op, spec in quota_config["costs"].items():
            if isinstance(spec, (int, float)):
                spec = {"cost": spec}
            bucket = spec.get("bucket", "data_api")
            if bucket not in self.buckets:
                raise ConfigError(f"settings.yaml quota.costs.{op}: unknown bucket '{bucket}'")
            self.costs[op] = {"cost": int(spec["cost"]), "bucket": bucket, "verified": bool(spec.get("verified", True))}
        override = os.getenv("YOUTUBE_DAILY_QUOTA")
        if override and override.isdigit():
            self.buckets["data_api"].daily_limit = int(override)
        self.warn_ratio = warn_ratio if warn_ratio is not None else float(quota_config.get("warn_ratio", 0.2))
        self.ledger_path = Path(ledger_path) if ledger_path else None

    # ----- ledger -----------------------------------------------------------------
    def _load(self) -> dict:
        today = pacific_today()
        if self.ledger_path and self.ledger_path.exists():
            try:
                data = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
            if data.get("date") == today:
                data.setdefault("used", {})
                data.setdefault("exhausted", [])
                data.setdefault("calls", [])
                return data
        return {"date": today, "used": {}, "exhausted": [], "calls": []}

    def _save(self, data: dict) -> None:
        if not self.ledger_path:
            self._memory = data
            return
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.ledger_path.parent, prefix=".quota.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, self.ledger_path)

    def _state(self) -> dict:
        if not self.ledger_path:
            mem = getattr(self, "_memory", None)
            if not mem or mem.get("date") != pacific_today():
                self._memory = {"date": pacific_today(), "used": {}, "exhausted": [], "calls": []}
            return self._memory
        return self._load()

    # ----- estimation -------------------------------------------------------------
    def cost_of(self, op: str) -> tuple[str, int] | None:
        spec = self.costs.get(op)
        return (spec["bucket"], spec["cost"]) if spec else None

    def estimate(self, ops: list[str]) -> QuotaEstimate:
        est = QuotaEstimate()
        for op in ops:
            spec = self.costs.get(op)
            if not spec:
                est.unknown_ops.append(op)
                continue
            est.by_bucket[spec["bucket"]] = est.by_bucket.get(spec["bucket"], 0) + spec["cost"]
            if not spec["verified"] and op not in est.unverified_ops:
                est.unverified_ops.append(op)
        return est

    def remaining(self) -> dict[str, dict]:
        state = self._state()
        out = {}
        for name, bucket in self.buckets.items():
            used = int(state["used"].get(name, 0))
            out[name] = {
                "unit": bucket.unit,
                "daily_limit": bucket.daily_limit,
                "used_estimate": used,
                "remaining_estimate": (bucket.daily_limit - used) if bucket.daily_limit is not None else None,
                "exhausted": name in state["exhausted"],
            }
        return out

    def check(self, ops: list[str]) -> list[str]:
        """Raise QuotaExceededError if ``ops`` would exceed a bucket; return warnings otherwise."""
        est = self.estimate(ops)
        rem = self.remaining()
        warnings: list[str] = []
        for op in est.unknown_ops:
            warnings.append(f"No quota cost configured for '{op}'; not counted.")
        for op in est.unverified_ops:
            warnings.append(f"Quota cost for '{op}' is an unverified estimate (not listed on Google's quota page).")
        for bucket, need in est.by_bucket.items():
            info = rem[bucket]
            if info["exhausted"]:
                raise QuotaExceededError(
                    f"Quota bucket '{bucket}' was reported exhausted by Google today ({pacific_today()} PT). "
                    "It resets at midnight Pacific Time."
                )
            left = info["remaining_estimate"]
            if left is None:
                continue
            if need > left:
                raise QuotaExceededError(
                    f"Estimated need {need} {info['unit']} in '{bucket}' but only ~{left} remain today "
                    f"(limit {info['daily_limit']}). Wait for the Pacific-midnight reset or request more quota."
                )
            limit = info["daily_limit"] or 0
            if limit and (left - need) < limit * self.warn_ratio:
                warnings.append(
                    f"Quota warning: '{bucket}' would have ~{left - need} of {limit} {info['unit']} left after this run."
                )
        return warnings

    # ----- accounting -------------------------------------------------------------
    def record(self, op: str, *, http_status: int | None = None, success: bool = True, request_id: str | None = None) -> None:
        """Record an attempted call. Google charges quota for failed requests too, so every attempt counts."""
        spec = self.costs.get(op)
        state = self._state()
        if spec:
            state["used"][spec["bucket"]] = int(state["used"].get(spec["bucket"], 0)) + spec["cost"]
        state["calls"].append(
            {
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "op": op,
                "cost": spec["cost"] if spec else None,
                "bucket": spec["bucket"] if spec else None,
                "http_status": http_status,
                "success": success,
                "request_id": request_id,
            }
        )
        state["calls"] = state["calls"][-500:]
        self._save(state)

    def mark_exhausted(self, op: str) -> str:
        spec = self.costs.get(op)
        bucket = spec["bucket"] if spec else "data_api"
        state = self._state()
        if bucket not in state["exhausted"]:
            state["exhausted"].append(bucket)
        self._save(state)
        return bucket

    def report(self) -> dict:
        return {"date_pacific": pacific_today(), "buckets": self.remaining(), "note": "Estimates only; Google Cloud Console is authoritative."}


def from_settings(settings: dict, state_dir: Path) -> QuotaManager:
    return QuotaManager(settings.get("quota", {}), Path(state_dir) / "quota_ledger.json")
