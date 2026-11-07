"""Bybit v5 public streams.
Spot:   wss://stream.bybit.com/v5/public/spot    publicTrade / kline / orderbook.50 / tickers
Linear: wss://stream.bybit.com/v5/public/linear  tickers (fundingRate, openInterest)
App-level ping {"op":"ping"} every 20 s as Bybit requires.
"""
from __future__ import annotations

import json

from ..events import MarketEvent
from .base import WSAdapter
from .binance import to_symbol

TF = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "12h": "720", "1d": "D", "1w": "W"}


class BybitWS(WSAdapter):
    name = "bybit"
    ping_interval = 20.0
    SPOT = "wss://stream.bybit.com/v5/public/spot"
    LINEAR = "wss://stream.bybit.com/v5/public/linear"

    def connections(self):
        ids = [s.replace("/", "") for s in self.symbols]
        spot = [{"op": "subscribe", "args": [a for i in ids for a in (f"publicTrade.{i}", f"kline.{TF[self.timeframe]}.{i}",
                                                                       f"orderbook.50.{i}", f"tickers.{i}")]}]
        lin = [{"op": "subscribe", "args": [f"tickers.{i}" for i in ids]}]
        if self.url_override:
            return [(self.url_override, spot)]
        return [(self.SPOT, spot), (self.LINEAR, lin)]

    def ping_message(self):
        return json.dumps({"op": "ping"})

    def parse(self, raw):
        m = json.loads(raw)
        topic = m.get("topic")
        if not topic:
            if m.get("op") == "subscribe" and m.get("success") is False:
                raise ValueError(f"bybit subscription failed: {m.get('ret_msg')}")
            return []
        out = []
        if topic.startswith("publicTrade."):
            for t in m["data"]:
                out.append(MarketEvent("trade", self.name, to_symbol(t["s"]), int(t["T"]), {
                    "price": float(t["p"]), "qty": float(t["v"]), "is_buyer_maker": t["S"] == "Sell"}, f"t{t['i']}"))
        elif topic.startswith("kline."):
            sym = to_symbol(topic.split(".")[-1])
            for k in m["data"]:
                out.append(MarketEvent("candle", self.name, sym, int(k["timestamp"]), {
                    "open_time": int(k["start"]), "close_time": int(k["end"]), "interval": k["interval"], "open": float(k["open"]),
                    "high": float(k["high"]), "low": float(k["low"]), "close": float(k["close"]), "volume": float(k["volume"]),
                    "closed": bool(k["confirm"])}, f"k{k['start']}-{k['timestamp']}"))
        elif topic.startswith("orderbook."):
            d = m["data"]
            kind = "book_snapshot" if m["type"] == "snapshot" else "book_delta"
            out.append(MarketEvent(kind, self.name, to_symbol(d["s"]), int(m["ts"]), {
                "first": int(d["u"]), "last": int(d["u"]), "bids": [(float(p), float(q)) for p, q in d["b"]],
                "asks": [(float(p), float(q)) for p, q in d["a"]]}, f"b{d['u']}-{d.get('seq')}"))
        elif topic.startswith("tickers."):
            d = m["data"]
            sym = to_symbol(d["symbol"])
            if "fundingRate" in d or "openInterest" in d:  # linear: deltas may omit fields
                if d.get("fundingRate"):
                    out.append(MarketEvent("funding", self.name, sym, int(m["ts"]), {
                        "rate": float(d["fundingRate"]), "next_funding_ms": int(d.get("nextFundingTime") or 0),
                        "mark": float(d["markPrice"]) if d.get("markPrice") else None}, f"f{m['ts']}"))
                if d.get("openInterest"):
                    out.append(MarketEvent("open_interest", self.name, sym, int(m["ts"]), {"oi": float(d["openInterest"])}, f"oi{m['ts']}"))
            elif d.get("lastPrice"):
                out.append(MarketEvent("ticker", self.name, sym, int(m["ts"]), {
                    "last": float(d["lastPrice"]), "volume_24h": float(d.get("volume24h") or 0),
                    "quote_volume_24h": float(d.get("turnover24h") or 0)}, f"tk{m['ts']}"))
        return out
