"""Local L2 order book with sequence checks.

Rules per venue (from their docs):
- Binance diff depth: after a REST snapshot with lastUpdateId L, drop events with u <= L;
  the first applied event must satisfy U <= L+1 <= u; afterwards each U must be prev_u + 1.
- Bybit: a 'snapshot' resets the book; deltas must have u greater than the last u.
- OKX: each update's prevSeqId must equal the previous seqId.
A gap sets `needs_resync`; the book refuses further deltas until a new snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..ta.orderflow import Book


class SequenceGap(RuntimeError):
    pass


@dataclass
class OrderBook:
    exchange: str
    symbol: str
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_seq: int | None = None
    needs_resync: bool = True
    first_after_snapshot: bool = False
    ts_ms: int = 0

    def snapshot(self, bids, asks, seq: int, ts_ms: int = 0) -> None:
        self.bids = {p: q for p, q in bids if q > 0}
        self.asks = {p: q for p, q in asks if q > 0}
        self.last_seq, self.needs_resync, self.first_after_snapshot, self.ts_ms = seq, False, True, ts_ms

    def _apply(self, bids, asks):
        for side, levels in ((self.bids, bids), (self.asks, asks)):
            for p, q in levels:
                if q == 0:
                    side.pop(p, None)
                else:
                    side[p] = q

    def delta(self, bids, asks, first: int, last: int, ts_ms: int = 0, prev: int | None = None) -> bool:
        """Apply an update; returns False if it was stale (already included). Raises SequenceGap on a gap."""
        if self.needs_resync or self.last_seq is None:
            raise SequenceGap(f"{self.exchange} {self.symbol}: no snapshot")
        if self.exchange == "binance":
            if last <= self.last_seq:
                return False
            ok = (first <= self.last_seq + 1 <= last) if self.first_after_snapshot else (first == self.last_seq + 1)
        elif self.exchange == "okx":
            ok = prev == self.last_seq
        else:  # bybit
            if last <= self.last_seq:
                return False
            ok = True
        if not ok:
            self.needs_resync = True
            raise SequenceGap(f"{self.exchange} {self.symbol}: gap after {self.last_seq} (got {first}..{last})")
        self._apply(bids, asks)
        self.last_seq, self.first_after_snapshot, self.ts_ms = last, False, ts_ms
        if self.bids and self.asks and max(self.bids) >= min(self.asks):
            self.needs_resync = True
            raise SequenceGap(f"{self.exchange} {self.symbol}: crossed book after update {last}")
        return True

    def top(self, depth: int = 50) -> Book:
        return Book(sorted(self.bids.items(), reverse=True)[:depth], sorted(self.asks.items())[:depth])

    def best(self) -> tuple[float | None, float | None]:
        return (max(self.bids) if self.bids else None, min(self.asks) if self.asks else None)
