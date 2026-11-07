from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["trade", "candle", "book_snapshot", "book_delta", "ticker", "funding", "open_interest"]


@dataclass
class MarketEvent:
    kind: Kind
    exchange: str
    symbol: str            # BTC/USDT
    ts_ms: int             # exchange event time
    data: dict
    event_id: str = ""     # used for duplicate suppression
    recv_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    source: str = "live"   # always "live" for websocket events; tests set "test"

    def meta(self, connection: str) -> dict:
        return {"exchange": self.exchange, "symbol": self.symbol, "timestamp_ms": self.ts_ms, "source": self.source,
                "connection": connection, "latency_ms": self.recv_ms - self.ts_ms}
