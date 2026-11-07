"""Binance spot + USD-M futures public streams (combined-stream format).
Spot:    wss://stream.binance.com:9443/stream?streams=btcusdt@trade/btcusdt@kline_1m/btcusdt@depth@100ms/btcusdt@ticker
Futures: wss://fstream.binance.com/stream?streams=btcusdt@markPrice@1s   (funding rate, mark price)
Binance sends protocol pings; the websockets library answers them. Open interest has no
public stream on Binance; it comes from REST (data/exchanges.py).
"""
from __future__ import annotations

import json

from ..events import MarketEvent
from .base import WSAdapter

QUOTES = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB", "EUR", "TRY")


def to_symbol(s: str) -> str:
    s = s.upper()
    for q in QUOTES:
        if s.endswith(q) and len(s) > len(q):
            return f"{s[:-len(q)]}/{q}"
    return s


class BinanceWS(WSAdapter):
    name = "binance"
    SPOT = "wss://stream.binance.com:9443/stream?streams="
    FUT = "wss://fstream.binance.com/stream?streams="

    def connections(self):
        ids = [s.replace("/", "").lower() for s in self.symbols]
        spot = "/".join(f"{i}@trade/{i}@kline_{self.timeframe}/{i}@depth@100ms/{i}@ticker" for i in ids)
        fut = "/".join(f"{i}@markPrice@1s" for i in ids)
        if self.url_override:
            return [(self.url_override, [])]
        return [(self.SPOT + spot, []), (self.FUT + fut, [])]

    def parse(self, raw):
        m = json.loads(raw)
        d = m.get("data", m)
        e = d.get("e")
        if e is None:
            return []
        sym = to_symbol(d["s"])
        if e == "trade":
            return [MarketEvent("trade", self.name, sym, int(d["T"]), {"price": float(d["p"]), "qty": float(d["q"]),
                                "is_buyer_maker": bool(d["m"])}, f"t{d['t']}")]
        if e == "kline":
            k = d["k"]
            return [MarketEvent("candle", self.name, sym, int(d["E"]), {
                "open_time": int(k["t"]), "close_time": int(k["T"]), "interval": k["i"], "open": float(k["o"]),
                "high": float(k["h"]), "low": float(k["l"]), "close": float(k["c"]), "volume": float(k["v"]),
                "closed": bool(k["x"])}, f"k{k['t']}-{d['E']}")]
        if e == "depthUpdate":
            return [MarketEvent("book_delta", self.name, sym, int(d["E"]), {
                "first": int(d["U"]), "last": int(d["u"]), "bids": [(float(p), float(q)) for p, q in d["b"]],
                "asks": [(float(p), float(q)) for p, q in d["a"]]}, f"d{d['u']}")]
        if e == "24hrTicker":
            return [MarketEvent("ticker", self.name, sym, int(d["E"]), {"last": float(d["c"]), "volume_24h": float(d["v"]),
                                "quote_volume_24h": float(d["q"])}, f"tk{d['E']}")]
        if e == "markPriceUpdate":
            return [MarketEvent("funding", self.name, sym, int(d["E"]), {"rate": float(d["r"]), "mark": float(d["p"]),
                                "next_funding_ms": int(d["T"])}, f"f{d['E']}")]
        return []
