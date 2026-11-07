"""Core data types and market-data validation."""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}/[A-Z0-9]{2,8}$")
TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"]
TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
              "4h": 14400, "12h": 43200, "1d": 86400, "1w": 604800}
DEFAULT_UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
                    "ADA/USDT", "DOGE/USDT", "LINK/USDT", "AVAX/USDT", "DOT/USDT"]
OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


class DataValidationError(ValueError):
    pass


def validate_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if not SYMBOL_RE.match(s):
        raise DataValidationError(f"invalid symbol {symbol!r}; expected e.g. BTC/USDT")
    return s


def validate_timeframe(tf: str) -> str:
    if tf not in TF_SECONDS:
        raise DataValidationError(f"invalid timeframe {tf!r}; one of {TIMEFRAMES}")
    return tf


def validate_ohlcv(df: pd.DataFrame, timeframe: str | None = None) -> pd.DataFrame:
    """Reject malformed candles instead of repairing them.

    Rules: required columns, UTC DatetimeIndex strictly increasing, no NaN/inf,
    positive prices, high >= max(open, close), low <= min(open, close), volume >= 0.
    Gaps are allowed (exchanges have outages) but reported in df.attrs["gaps"].
    """
    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(f"missing columns {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise DataValidationError("index must be a DatetimeIndex")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise DataValidationError("timestamps must be strictly increasing")
    vals = df[OHLCV_COLUMNS].to_numpy(dtype=float)
    if not pd.notna(vals).all() or not (abs(vals) != math.inf).all():
        raise DataValidationError("NaN or inf in candles")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataValidationError("non-positive price")
    if (df["volume"] < 0).any():
        raise DataValidationError("negative volume")
    body_hi = df[["open", "close"]].max(axis=1)
    body_lo = df[["open", "close"]].min(axis=1)
    if (df["high"] + 1e-12 < body_hi).any() or (df["low"] - 1e-12 > body_lo).any():
        raise DataValidationError("high/low inconsistent with open/close")
    gaps = 0
    if timeframe and len(df) > 1:
        step = pd.Timedelta(seconds=TF_SECONDS[timeframe])
        gaps = int((df.index.to_series().diff().dropna() > step).sum())
    df.attrs["gaps"] = gaps
    return df


@dataclass
class MarketMeta:
    """Provenance attached to every market-data payload shown to a user."""
    exchange: str
    symbol: str
    timestamp_ms: int          # exchange timestamp of the newest datum
    received_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    source: Literal["live", "fixture", "synthetic"] = "live"

    @property
    def age_seconds(self) -> float:
        return max(0.0, (self.received_ms - self.timestamp_ms) / 1000)

    def as_dict(self) -> dict:
        return {"exchange": self.exchange, "symbol": self.symbol, "timestamp_ms": self.timestamp_ms,
                "received_ms": self.received_ms, "age_seconds": round(self.age_seconds, 3),
                "source": self.source}


@dataclass
class Signal:
    strategy: str
    symbol: str
    side: int                 # +1 long, -1 short
    entry: float
    stop: float
    target: float
    bar_time: pd.Timestamp
    reason: str = ""

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_risk(self) -> float:
        r = self.risk_per_unit
        return abs(self.target - self.entry) / r if r > 0 else 0.0


@dataclass
class Position:
    symbol: str
    side: int
    qty: float
    entry: float
    stop: float
    target: float
    strategy: str = ""
    opened_at: pd.Timestamp | None = None

    @property
    def open_risk(self) -> float:
        return abs(self.entry - self.stop) * self.qty

    @property
    def notional(self) -> float:
        return self.entry * self.qty

    def unrealized(self, price: float) -> float:
        return (price - self.entry) * self.qty * self.side
