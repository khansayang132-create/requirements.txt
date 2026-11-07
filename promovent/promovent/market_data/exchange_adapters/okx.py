"""OKX v5 public streams.
Public:   wss://ws.okx.com:8443/ws/v5/public    trades, books, tickers, funding-rate, open-interest
Business: wss://ws.okx.com:8443/ws/v5/business  candle{tf}
App-level ping: text "ping" every 25 s (OKX closes idle sockets after 30 s).
"""
from __future__ import annotations

import json

from ..events import MarketEvent
from .base import WSAdapter

TF = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "12h": "12Hutc",
      "1d": "1Dutc", "1w": "1Wutc"}


class OKXWS(WSAdapter):
    name = "okx"
    ping_interval = 25.0
    PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"
    BUSINESS = "wss://ws.okx.com:8443/ws/v5/business"

    def connections(self):
        ids = [s.replace("/", "-") for s in self.symbols]
        pub = [{"op": "subscribe", "args": [a for i in ids for a in (
            {"channel": "trades", "instId": i}, {"channel": "books", "instId": i}, {"channel": "tickers", "instId": i},
            {"channel": "funding-rate", "instId": i + "-SWAP"}, {"channel": "open-interest", "instId": i + "-SWAP"})]}]
        biz = [{"op": "subscribe", "args": [{"channel": f"candle{TF[self.timeframe]}", "instId": i} for i in ids]}]
        if self.url_override:
            return [(self.url_override, pub)]
        return [(self.PUBLIC, pub), (self.BUSINESS, biz)]

    def ping_message(self):
        return "ping"

    @staticmethod
    def sym(inst: str) -> str:
        parts = inst.split("-")
        return f"{parts[0]}/{parts[1]}"

    def parse(self, raw):
        if raw in ("pong", b"pong"):
            return []
        m = json.loads(raw)
        if m.get("event") == "error":
            raise ValueError(f"okx subscription error {m.get('code')}: {m.get('msg')}")
        arg, data = m.get("arg"), m.get("data")
        if not arg or not data:
            return []
        ch, sym = arg["channel"], self.sym(arg["instId"])
        out = []
        if ch == "trades":
            for t in data:
                out.append(MarketEvent("trade", self.name, sym, int(t["ts"]), {"price": float(t["px"]), "qty": float(t["sz"]),
                                       "is_buyer_maker": t["side"] == "sell"}, f"t{t['tradeId']}"))
        elif ch.startswith("candle"):
            for k in data:
                out.append(MarketEvent("candle", self.name, sym, int(k[0]), {
                    "open_time": int(k[0]), "close_time": None, "interval": ch[6:], "open": float(k[1]), "high": float(k[2]),
                    "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]), "closed": k[8] == "1"},
                    f"k{k[0]}-{k[4]}-{k[5]}-{k[8]}"))
        elif ch.startswith("books"):
            for b in data:
                kind = "book_snapshot" if m.get("action") == "snapshot" else "book_delta"
                out.append(MarketEvent(kind, self.name, sym, int(b["ts"]), {
                    "first": int(b.get("prevSeqId", -1)), "last": int(b["seqId"]), "prev": int(b.get("prevSeqId", -1)),
                    "bids": [(float(x[0]), float(x[1])) for x in b["bids"]], "asks": [(float(x[0]), float(x[1])) for x in b["asks"]]},
                    f"b{b['seqId']}"))
        elif ch == "tickers":
            for t in data:
                out.append(MarketEvent("ticker", self.name, sym, int(t["ts"]), {"last": float(t["last"]), "volume_24h": float(t["vol24h"]),
                                       "quote_volume_24h": float(t.get("volCcy24h") or 0)}, f"tk{t['ts']}"))
        elif ch == "funding-rate":
            for f in data:
                out.append(MarketEvent("funding", self.name, sym, int(f.get("ts") or f["fundingTime"]), {
                    "rate": float(f["fundingRate"]), "next_funding_ms": int(f.get("nextFundingTime") or 0)}, f"f{f.get('ts')}"))
        elif ch == "open-interest":
            for o in data:
                out.append(MarketEvent("open_interest", self.name, sym, int(o["ts"]), {"oi": float(o["oi"])}, f"oi{o['ts']}"))
        return out
