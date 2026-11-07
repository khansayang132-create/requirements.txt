"""Event sanity checks before anything downstream sees an event."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from .events import MarketEvent


@dataclass
class ValidatorStats:
    accepted: int = 0
    duplicates: int = 0
    future: int = 0
    too_old: int = 0
    out_of_order: int = 0
    invalid: int = 0

    def as_dict(self):
        return self.__dict__.copy()


@dataclass
class DataValidator:
    max_future_ms: int = 5_000        # exchange clock ahead of ours by more than this => reject
    max_age_ms: int = 120_000         # event older than this when received => reject as stale
    dedupe_size: int = 50_000
    stats: ValidatorStats = field(default_factory=ValidatorStats)
    _seen: OrderedDict = field(default_factory=OrderedDict)
    _last_trade_ts: dict = field(default_factory=dict)

    def check(self, ev: MarketEvent) -> tuple[bool, str]:
        if not ev.symbol or "/" not in ev.symbol or ev.ts_ms <= 0:
            self.stats.invalid += 1
            return False, "invalid symbol or timestamp"
        if ev.ts_ms - ev.recv_ms > self.max_future_ms:
            self.stats.future += 1
            return False, f"timestamp {ev.ts_ms - ev.recv_ms} ms in the future"
        if ev.recv_ms - ev.ts_ms > self.max_age_ms and ev.kind != "candle":
            self.stats.too_old += 1
            return False, f"event {ev.recv_ms - ev.ts_ms} ms old"
        if ev.kind in ("trade", "ticker"):
            price = ev.data.get("price", ev.data.get("last"))
            if price is None or price <= 0:
                self.stats.invalid += 1
                return False, "non-positive price"
        if ev.kind == "candle":
            d = ev.data
            if not (d["low"] <= min(d["open"], d["close"]) and d["high"] >= max(d["open"], d["close"]) and d["low"] > 0
                    and d["volume"] >= 0):
                self.stats.invalid += 1
                return False, "inconsistent candle"
        key = (ev.exchange, ev.symbol, ev.kind, ev.event_id)
        if ev.event_id:
            if key in self._seen:
                self.stats.duplicates += 1
                return False, "duplicate"
            self._seen[key] = None
            if len(self._seen) > self.dedupe_size:
                self._seen.popitem(last=False)
        if ev.kind == "trade":
            k = (ev.exchange, ev.symbol)
            last = self._last_trade_ts.get(k, 0)
            if ev.ts_ms + 1_000 < last:  # trades may share a ms or arrive slightly out of order
                self.stats.out_of_order += 1
                return False, "trade out of order"
            self._last_trade_ts[k] = max(last, ev.ts_ms)
        self.stats.accepted += 1
        return True, ""
