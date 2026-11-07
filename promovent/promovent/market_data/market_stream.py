"""MarketStream: adapters + connections + validation + books + candles.

`snapshot()` gives, per symbol, the last price with exchange, timestamp, data source
("live") and the connection's status, so nothing is shown without provenance.
Book snapshots for Binance come from REST (diff stream needs one); Bybit and OKX send
snapshots on the socket. A sequence gap marks the book for resync and fetches a new one.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from .candle_processor import CandleProcessor
from .data_validator import DataValidator
from .events import MarketEvent
from .exchange_adapters import WS_ADAPTERS
from .orderbook import OrderBook, SequenceGap
from .websocket_manager import WSConnection

log = logging.getLogger("promovent.stream")


class MarketStream:
    def __init__(self, exchange: str, symbols: list[str], timeframe: str = "1m", url: str | None = None,
                 stale_after: float = 30.0, snapshot_fetcher: Callable[[str], tuple[list, list, int]] | None = None):
        self.adapter = WS_ADAPTERS[exchange](symbols, timeframe, url)
        self.exchange, self.symbols = exchange, symbols
        self.validator = DataValidator()
        self.candles = CandleProcessor(timeframe)
        self.books: dict[str, OrderBook] = {s: OrderBook(exchange, s) for s in symbols}
        self.last: dict[str, dict] = {}
        self.funding: dict[str, dict] = {}
        self.open_interest: dict[str, dict] = {}
        self.liquidations: list[dict] = []
        self.subscribers: list[Callable[[MarketEvent], None]] = []
        self.rejected: dict[str, int] = {}
        self.snapshot_fetcher = snapshot_fetcher
        self.conns = [WSConnection(u, subs, self._on_raw, self.adapter.ping_message, self.adapter.ping_interval,
                                   stale_after, self.adapter.max_msgs_per_sec) for u, subs in self.adapter.connections()]
        self._buffer: dict[str, list[MarketEvent]] = {}

    def conn_state(self) -> str:
        states = {c.status.state for c in self.conns}
        return "CONNECTED" if states == {"CONNECTED"} else ",".join(sorted(states))

    def _on_raw(self, raw):
        try:
            events = self.adapter.parse(raw)
        except (ValueError, KeyError, TypeError) as e:
            self.rejected["parse"] = self.rejected.get("parse", 0) + 1
            log.warning("parse error %s: %s", self.exchange, e)
            return
        for ev in events:
            ok, why = self.validator.check(ev)
            if not ok:
                self.rejected[why.split(" ")[0]] = self.rejected.get(why.split(" ")[0], 0) + 1
                continue
            self.handle(ev)

    def handle(self, ev: MarketEvent):
        s = ev.symbol
        if ev.kind in ("trade", "ticker"):
            price = ev.data.get("price", ev.data.get("last"))
            prev = self.last.get(s, {})
            self.last[s] = {"price": price, "ts_ms": ev.ts_ms, "kind": ev.kind,
                            "volume_24h": ev.data.get("volume_24h", prev.get("volume_24h"))}
        elif ev.kind == "candle":
            self.candles.on_kline(ev)
        elif ev.kind == "funding":
            self.funding[s] = {**ev.data, "ts_ms": ev.ts_ms}
        elif ev.kind == "open_interest":
            self.open_interest[s] = {**ev.data, "ts_ms": ev.ts_ms}
        elif ev.kind == "liquidation":
            self.liquidations.append({"symbol": s, **ev.data, "ts_ms": ev.ts_ms})
            del self.liquidations[:-200]
        elif ev.kind in ("book_snapshot", "book_delta") and s in self.books:
            self._book(ev)
        for cb in self.subscribers:
            cb(ev)

    def _book(self, ev: MarketEvent):
        b = self.books[ev.symbol]
        d = ev.data
        if ev.kind == "book_snapshot":
            b.snapshot(d["bids"], d["asks"], d["last"], ev.ts_ms)
            return
        if b.needs_resync:
            if self.exchange == "binance" and self.snapshot_fetcher:
                self._buffer.setdefault(ev.symbol, []).append(ev)
                if len(self._buffer[ev.symbol]) == 1:
                    try:
                        bids, asks, seq = self.snapshot_fetcher(ev.symbol)
                        b.snapshot(bids, asks, seq)
                    except Exception as e:  # REST blocked/unavailable: keep waiting, book stays unusable
                        self.rejected["book_snapshot"] = self.rejected.get("book_snapshot", 0) + 1
                        log.warning("book snapshot failed %s %s: %s", self.exchange, ev.symbol, e)
                        self._buffer[ev.symbol].clear()
                        return
                pending, self._buffer[ev.symbol] = self._buffer[ev.symbol], []
                for p in pending:
                    self._delta(b, p)
            return
        self._delta(b, ev)

    def _delta(self, b: OrderBook, ev: MarketEvent):
        d = ev.data
        try:
            b.delta(d["bids"], d["asks"], d["first"], d["last"], ev.ts_ms, d.get("prev"))
        except SequenceGap as e:
            self.rejected["book_gap"] = self.rejected.get("book_gap", 0) + 1
            log.warning("%s", e)

    def snapshot(self) -> dict:
        now = int(time.time() * 1000)
        conn = self.conn_state()
        out = {}
        for s in self.symbols:
            last = self.last.get(s)
            bb, ba = self.books[s].best()
            out[s] = {"exchange": self.exchange, "symbol": s, "source": "live", "connection": conn,
                      "price": last["price"] if last else None, "timestamp_ms": last["ts_ms"] if last else None,
                      "age_s": round((now - last["ts_ms"]) / 1000, 1) if last else None,
                      "best_bid": bb, "best_ask": ba, "book_ok": not self.books[s].needs_resync,
                      "funding": self.funding.get(s), "open_interest": self.open_interest.get(s)}
        return {"exchange": self.exchange, "connections": [c.status.as_dict() for c in self.conns], "symbols": out,
                "validator": self.validator.stats.as_dict(), "rejected": self.rejected,
                "liquidations": self.liquidations[-50:], "correlations_1m": self.correlations()}

    def correlations(self) -> dict:
        """Correlation of 1m close-to-close returns between streamed symbols (closed candles only)."""
        import numpy as np
        import pandas as pd
        rets = {s: self.candles.frame(self.exchange, s)["close"].pipe(np.log).diff() for s in self.symbols}
        df = pd.DataFrame({k: v for k, v in rets.items() if len(v) > 20}).dropna()
        if df.shape[1] < 2 or len(df) < 20:
            return {"available": False, "reason": "needs >= 20 closed 1m candles per symbol"}
        c = df.corr().round(3)
        return {"available": True, "n": len(df), "matrix": {a: c[a].to_dict() for a in c.columns}}

    async def run(self):
        await asyncio.gather(*(c.run() for c in self.conns))

    def stop(self):
        for c in self.conns:
            c.stop()
