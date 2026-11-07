"""Candles from streams. Only CLOSED candles go into history (forming candles would repaint signals)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import pandas as pd

from ..models import TF_SECONDS
from .events import MarketEvent


@dataclass
class CandleProcessor:
    timeframe: str = "1m"
    maxlen: int = 2000
    closed: dict[tuple[str, str], deque] = field(default_factory=dict)
    forming: dict[tuple[str, str], dict] = field(default_factory=dict)

    def on_kline(self, ev: MarketEvent) -> dict | None:
        """Returns the candle dict when a candle closes."""
        k = (ev.exchange, ev.symbol)
        d = ev.data
        cur = self.forming.get(k)
        out = None
        if cur and d["open_time"] > cur["open_time"]:
            # venue skipped the explicit close message (OKX may): previous forming candle is complete
            out = self._close(k, cur)
        if d["closed"]:
            out = self._close(k, d)
            self.forming.pop(k, None)
        else:
            self.forming[k] = d
        return out

    def on_trade(self, ev: MarketEvent) -> dict | None:
        """Builds candles from trades for venues/streams without klines."""
        k = (ev.exchange, ev.symbol)
        step = TF_SECONDS[self.timeframe] * 1000
        start = ev.ts_ms - ev.ts_ms % step
        p, q = ev.data["price"], ev.data["qty"]
        cur = self.forming.get(k)
        out = None
        if cur and start > cur["open_time"]:
            out = self._close(k, {**cur, "closed": True})
            cur = None
        if cur is None:
            self.forming[k] = {"open_time": start, "open": p, "high": p, "low": p, "close": p, "volume": q, "closed": False}
        else:
            cur.update(high=max(cur["high"], p), low=min(cur["low"], p), close=p, volume=cur["volume"] + q)
        return out

    def _close(self, k, d) -> dict:
        dq = self.closed.setdefault(k, deque(maxlen=self.maxlen))
        c = {f: d[f] for f in ("open_time", "open", "high", "low", "close", "volume")}
        if dq and dq[-1]["open_time"] == c["open_time"]:
            dq[-1] = c
        elif not dq or c["open_time"] > dq[-1]["open_time"]:
            dq.append(c)
        return c

    def frame(self, exchange: str, symbol: str) -> pd.DataFrame:
        dq = self.closed.get((exchange, symbol), ())
        if not dq:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame(list(dq))
        df.index = pd.to_datetime(df.pop("open_time"), unit="ms", utc=True)
        df.index.name = "time"
        return df
