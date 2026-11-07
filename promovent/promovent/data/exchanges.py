"""Unified public market-data adapters: Binance, Bybit, OKX, Coinbase Exchange.

Read-only. No adapter here can place orders or withdraw; there is no signed
endpoint in this module. Each adapter turns the exchange's documented REST
format into the same shapes:

  ohlcv  -> validated DataFrame (UTC index, open/high/low/close/volume), oldest first,
            in-progress candle dropped (a forming candle would repaint every signal)
  book   -> orderflow.Book
  trades -> [{price, qty, is_buyer_maker, ts}]
  funding-> {rate, next_funding_ms, open_interest} (perpetual swaps; None where unsupported)

Every result carries MarketMeta (exchange, symbol, timestamp, freshness, source).
Failures raise ExchangeError; nothing is filled in or guessed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import pandas as pd

from ..models import MarketMeta, TF_SECONDS, validate_ohlcv, validate_symbol, validate_timeframe
from ..ta.orderflow import Book


class ExchangeError(RuntimeError):
    pass


@dataclass
class OHLCVResult:
    df: pd.DataFrame
    meta: MarketMeta


def _now_ms() -> int:
    return int(time.time() * 1000)


def _frame(rows: list[tuple[int, float, float, float, float, float]], tf: str, now_ms: int) -> pd.DataFrame:
    if not rows:
        raise ExchangeError("no candles returned")
    rows = sorted(rows, key=lambda r: r[0])
    step = TF_SECONDS[tf] * 1000
    rows = [r for r in rows if r[0] + step <= now_ms]  # closed candles only
    if not rows:
        raise ExchangeError("only an in-progress candle was returned")
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    df.index.name = "time"
    return validate_ohlcv(df.astype(float), tf)


class Adapter:
    name = "base"
    base_url = ""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 10.0):
        self.client = client or httpx.Client(timeout=timeout, headers={"User-Agent": "promovent/2.0"})

    def _get(self, path: str, params: dict | None = None, base: str | None = None):
        url = (base or self.base_url) + path
        try:
            r = self.client.get(url, params=params)
        except httpx.HTTPError as e:
            raise ExchangeError(f"{self.name}: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise ExchangeError(f"{self.name}: HTTP {r.status_code} for {path}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise ExchangeError(f"{self.name}: non-JSON response") from e

    # pure parsers (tested against documented response shapes)
    def market_id(self, symbol: str) -> str:
        raise NotImplementedError

    def ohlcv(self, symbol: str, tf: str, limit: int = 500, now_ms: int | None = None) -> OHLCVResult:
        raise NotImplementedError

    def book(self, symbol: str, depth: int = 50) -> tuple[Book, MarketMeta]:
        raise NotImplementedError

    def trades(self, symbol: str, limit: int = 500) -> tuple[list[dict], MarketMeta]:
        raise NotImplementedError

    def funding(self, symbol: str) -> dict | None:
        return None

    def health(self) -> dict:
        t0 = time.time()
        try:
            self.ohlcv("BTC/USDT", "1m", limit=2)
            return {"exchange": self.name, "ok": True, "latency_ms": round((time.time() - t0) * 1000)}
        except ExchangeError as e:
            return {"exchange": self.name, "ok": False, "error": str(e)}


class Binance(Adapter):
    name = "binance"
    base_url = "https://api.binance.com"
    futures_url = "https://fapi.binance.com"

    def market_id(self, symbol: str) -> str:
        return validate_symbol(symbol).replace("/", "")

    @staticmethod
    def parse_klines(raw: list, tf: str, now_ms: int) -> pd.DataFrame:
        return _frame([(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in raw],
                      tf, now_ms)

    def ohlcv(self, symbol, tf, limit=500, now_ms=None):
        validate_timeframe(tf)
        raw = self._get("/api/v3/klines", {"symbol": self.market_id(symbol), "interval": tf, "limit": min(limit, 1000)})
        now = now_ms or _now_ms()
        df = self.parse_klines(raw, tf, now)
        return OHLCVResult(df, MarketMeta(self.name, symbol, int(df.index[-1].value // 10**6) + TF_SECONDS[tf] * 1000, now))

    @staticmethod
    def parse_book(raw: dict) -> Book:
        return Book([(float(p), float(q)) for p, q in raw["bids"]], [(float(p), float(q)) for p, q in raw["asks"]]).validate()

    def book(self, symbol, depth=50):
        raw = self._get("/api/v3/depth", {"symbol": self.market_id(symbol), "limit": depth})
        now = _now_ms()
        return self.parse_book(raw), MarketMeta(self.name, symbol, now, now)

    @staticmethod
    def parse_trades(raw: list) -> list[dict]:
        return [{"price": float(t["price"]), "qty": float(t["qty"]), "is_buyer_maker": bool(t["isBuyerMaker"]),
                 "ts": int(t["time"])} for t in raw]

    def trades(self, symbol, limit=500):
        tr = self.parse_trades(self._get("/api/v3/trades", {"symbol": self.market_id(symbol), "limit": limit}))
        return tr, MarketMeta(self.name, symbol, tr[-1]["ts"] if tr else _now_ms())

    @staticmethod
    def parse_funding(premium: dict, oi: dict | None) -> dict:
        return {"rate": float(premium["lastFundingRate"]), "next_funding_ms": int(premium["nextFundingTime"]),
                "mark": float(premium["markPrice"]), "open_interest": float(oi["openInterest"]) if oi else None}

    def funding(self, symbol):
        mid = self.market_id(symbol)
        p = self._get("/fapi/v1/premiumIndex", {"symbol": mid}, base=self.futures_url)
        oi = self._get("/fapi/v1/openInterest", {"symbol": mid}, base=self.futures_url)
        return self.parse_funding(p, oi)


class Bybit(Adapter):
    name = "bybit"
    base_url = "https://api.bybit.com"
    TF = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240",
          "12h": "720", "1d": "D", "1w": "W"}

    def market_id(self, symbol):
        return validate_symbol(symbol).replace("/", "")

    @staticmethod
    def _check(raw: dict) -> dict:
        if raw.get("retCode") != 0:
            raise ExchangeError(f"bybit: retCode {raw.get('retCode')}: {raw.get('retMsg')}")
        return raw["result"]

    @classmethod
    def parse_klines(cls, raw: dict, tf: str, now_ms: int) -> pd.DataFrame:
        rows = cls._check(raw)["list"]
        return _frame([(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in rows],
                      tf, now_ms)

    def ohlcv(self, symbol, tf, limit=500, now_ms=None):
        validate_timeframe(tf)
        raw = self._get("/v5/market/kline", {"category": "spot", "symbol": self.market_id(symbol),
                                              "interval": self.TF[tf], "limit": min(limit, 1000)})
        now = now_ms or _now_ms()
        df = self.parse_klines(raw, tf, now)
        return OHLCVResult(df, MarketMeta(self.name, symbol, int(df.index[-1].value // 10**6) + TF_SECONDS[tf] * 1000, now))

    @classmethod
    def parse_book(cls, raw: dict) -> Book:
        r = cls._check(raw)
        return Book([(float(p), float(q)) for p, q in r["b"]], [(float(p), float(q)) for p, q in r["a"]]).validate()

    def book(self, symbol, depth=50):
        raw = self._get("/v5/market/orderbook", {"category": "spot", "symbol": self.market_id(symbol), "limit": depth})
        return self.parse_book(raw), MarketMeta(self.name, symbol, int(raw["result"]["ts"]))

    @classmethod
    def parse_trades(cls, raw: dict) -> list[dict]:
        out = [{"price": float(t["price"]), "qty": float(t["size"]), "is_buyer_maker": t["side"] == "Sell",
                "ts": int(t["time"])} for t in cls._check(raw)["list"]]
        return sorted(out, key=lambda t: t["ts"])

    def trades(self, symbol, limit=500):
        tr = self.parse_trades(self._get("/v5/market/recent-trade", {"category": "spot", "symbol": self.market_id(symbol),
                                                                       "limit": min(limit, 60)}))
        return tr, MarketMeta(self.name, symbol, tr[-1]["ts"] if tr else _now_ms())

    @classmethod
    def parse_funding(cls, raw: dict) -> dict:
        t = cls._check(raw)["list"][0]
        return {"rate": float(t["fundingRate"]), "next_funding_ms": int(t["nextFundingTime"]),
                "mark": float(t["markPrice"]), "open_interest": float(t["openInterest"])}

    def funding(self, symbol):
        return self.parse_funding(self._get("/v5/market/tickers", {"category": "linear", "symbol": self.market_id(symbol)}))


class OKX(Adapter):
    name = "okx"
    base_url = "https://www.okx.com"
    TF = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H",
          "12h": "12Hutc", "1d": "1Dutc", "1w": "1Wutc"}

    def market_id(self, symbol):
        return validate_symbol(symbol).replace("/", "-")

    @staticmethod
    def _check(raw: dict) -> list:
        if str(raw.get("code")) != "0":
            raise ExchangeError(f"okx: code {raw.get('code')}: {raw.get('msg')}")
        return raw["data"]

    @classmethod
    def parse_klines(cls, raw: dict, tf: str, now_ms: int) -> pd.DataFrame:
        rows = [k for k in cls._check(raw) if len(k) < 9 or k[8] == "1"]  # confirm flag: 1 = closed
        return _frame([(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in rows],
                      tf, now_ms)

    def ohlcv(self, symbol, tf, limit=300, now_ms=None):
        """Recent candles (300 max per call), then older pages from /history-candles (100 per call)
        until `limit` closed candles are collected or history runs out."""
        validate_timeframe(tf)
        inst = self.market_id(symbol)
        raw = self._get("/api/v5/market/candles", {"instId": inst, "bar": self.TF[tf], "limit": min(limit, 300)})
        rows = list(self._check(raw))
        while len(rows) < limit + 1 and rows:
            oldest = min(int(k[0]) for k in rows)
            page = self._check(self._get("/api/v5/market/history-candles",
                                         {"instId": inst, "bar": self.TF[tf], "after": oldest, "limit": 100}))
            if not page:
                break
            rows += page
            time.sleep(0.11)  # history-candles: 10 requests / 2 s per IP
        now = now_ms or _now_ms()
        seen, uniq = set(), []
        for k in rows:
            if k[0] not in seen:
                seen.add(k[0])
                uniq.append(k)
        df = self.parse_klines({"code": "0", "data": uniq}, tf, now).iloc[-limit:]
        return OHLCVResult(df, MarketMeta(self.name, symbol, int(df.index[-1].value // 10**6) + TF_SECONDS[tf] * 1000, now))

    @classmethod
    def parse_book(cls, raw: dict) -> Book:
        d = cls._check(raw)[0]
        return Book([(float(x[0]), float(x[1])) for x in d["bids"]], [(float(x[0]), float(x[1])) for x in d["asks"]]).validate()

    def book(self, symbol, depth=50):
        raw = self._get("/api/v5/market/books", {"instId": self.market_id(symbol), "sz": depth})
        return self.parse_book(raw), MarketMeta(self.name, symbol, int(raw["data"][0]["ts"]))

    @classmethod
    def parse_trades(cls, raw: dict) -> list[dict]:
        out = [{"price": float(t["px"]), "qty": float(t["sz"]), "is_buyer_maker": t["side"] == "sell",
                "ts": int(t["ts"])} for t in cls._check(raw)]
        return sorted(out, key=lambda t: t["ts"])

    def trades(self, symbol, limit=500):
        tr = self.parse_trades(self._get("/api/v5/market/trades", {"instId": self.market_id(symbol), "limit": min(limit, 500)}))
        return tr, MarketMeta(self.name, symbol, tr[-1]["ts"] if tr else _now_ms())

    @classmethod
    def parse_funding(cls, raw: dict, oi: dict | None = None) -> dict:
        d = cls._check(raw)[0]
        return {"rate": float(d["fundingRate"]), "next_funding_ms": int(d["nextFundingTime"]), "mark": None,
                "open_interest": float(cls._check(oi)[0]["oi"]) if oi else None}

    def funding(self, symbol):
        inst = self.market_id(symbol) + "-SWAP"
        return self.parse_funding(self._get("/api/v5/public/funding-rate", {"instId": inst}),
                                  self._get("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst}))


class Coinbase(Adapter):
    name = "coinbase"
    base_url = "https://api.exchange.coinbase.com"
    GRAN = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}  # 6h exists; not in our list

    def market_id(self, symbol):
        return validate_symbol(symbol).replace("/", "-")

    @staticmethod
    def parse_candles(raw: list, tf: str, now_ms: int) -> pd.DataFrame:
        # Coinbase order: [time_s, low, high, open, close, volume]
        return _frame([(int(k[0]) * 1000, float(k[3]), float(k[2]), float(k[1]), float(k[4]), float(k[5])) for k in raw],
                      tf, now_ms)

    def ohlcv(self, symbol, tf, limit=300, now_ms=None):
        validate_timeframe(tf)
        if tf not in self.GRAN:
            raise ExchangeError(f"coinbase: timeframe {tf} not offered (supported: {sorted(self.GRAN)})")
        raw = self._get(f"/products/{self.market_id(symbol)}/candles", {"granularity": self.GRAN[tf]})
        now = now_ms or _now_ms()
        df = self.parse_candles(raw, tf, now).iloc[-limit:]
        return OHLCVResult(df, MarketMeta(self.name, symbol, int(df.index[-1].value // 10**6) + TF_SECONDS[tf] * 1000, now))

    @staticmethod
    def parse_book(raw: dict) -> Book:
        return Book([(float(p), float(q)) for p, q, *_ in raw["bids"]], [(float(p), float(q)) for p, q, *_ in raw["asks"]]).validate()

    def book(self, symbol, depth=50):
        raw = self._get(f"/products/{self.market_id(symbol)}/book", {"level": 2})
        now = _now_ms()
        b = self.parse_book(raw)
        return Book(b.bids[:depth], b.asks[:depth]), MarketMeta(self.name, symbol, now, now)

    @staticmethod
    def parse_trades(raw: list) -> list[dict]:
        # Coinbase "side" is the maker side: side == "buy" means the taker sold.
        out = [{"price": float(t["price"]), "qty": float(t["size"]), "is_buyer_maker": t["side"] == "buy",
                "ts": int(pd.Timestamp(t["time"]).value // 10**6)} for t in raw]
        return sorted(out, key=lambda t: t["ts"])

    def trades(self, symbol, limit=500):
        tr = self.parse_trades(self._get(f"/products/{self.market_id(symbol)}/trades", {"limit": min(limit, 1000)}))
        return tr, MarketMeta(self.name, symbol, tr[-1]["ts"] if tr else _now_ms())


ADAPTERS: dict[str, type[Adapter]] = {"binance": Binance, "bybit": Bybit, "okx": OKX, "coinbase": Coinbase}


def get_adapter(name: str, client: httpx.Client | None = None) -> Adapter:
    try:
        return ADAPTERS[name.lower()](client)
    except KeyError:
        raise ExchangeError(f"unknown exchange {name!r}; one of {sorted(ADAPTERS)}") from None


def cross_exchange_prices(symbol: str, adapters: list[Adapter]) -> dict:
    """Strategy H (monitoring only): last close per exchange and the max spread in bps.
    Exchanges that fail are listed under `errors`, never given a price."""
    prices, errors = {}, {}
    for a in adapters:
        try:
            r = a.ohlcv(symbol, "1m", limit=3)
            prices[a.name] = {"close": float(r.df["close"].iloc[-1]), **r.meta.as_dict()}
        except ExchangeError as e:
            errors[a.name] = str(e)
    spread_bps = None
    if len(prices) >= 2:
        cl = [p["close"] for p in prices.values()]
        spread_bps = (max(cl) - min(cl)) / min(cl) * 1e4
    return {"symbol": symbol, "prices": prices, "errors": errors, "max_spread_bps": spread_bps,
            "note": "gross of fees, transfer time and withdrawal limits; not an arbitrage signal"}
