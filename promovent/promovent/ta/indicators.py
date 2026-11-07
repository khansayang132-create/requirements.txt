"""Causal technical indicators. Every value at bar i uses bars <= i only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0).where(up.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()],
                     axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def vwap(df: pd.DataFrame, session: str = "D") -> pd.Series:
    """Session VWAP, reset at each UTC session boundary (default daily)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    key = df.index.floor(session)
    pv = (tp * df["volume"]).groupby(key).cumsum()
    v = df["volume"].groupby(key).cumsum()
    return (pv / v.replace(0, np.nan)).ffill()


def rolling_vwap(df: pd.DataFrame, n: int = 50) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return (tp * df["volume"]).rolling(n, min_periods=n).sum() / df["volume"].rolling(n, min_periods=n).sum()


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    m = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"mid": m, "upper": m + k * sd, "lower": m - k * sd, "width": (2 * k * sd) / m})


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def volume_zscore(volume: pd.Series, n: int = 50) -> pd.Series:
    m = volume.rolling(n, min_periods=n).mean()
    sd = volume.rolling(n, min_periods=n).std(ddof=0)
    return (volume - m) / sd.replace(0, np.nan)


def realized_vol(close: pd.Series, n: int = 50) -> pd.Series:
    return np.log(close).diff().rolling(n, min_periods=n).std(ddof=0)


def fib_levels(swing_low: float, swing_high: float) -> dict[str, float]:
    """Retracement levels measured down from swing_high."""
    r = swing_high - swing_low
    return {f"{k:.3f}": swing_high - r * k for k in (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)}


def volume_profile(df: pd.DataFrame, bins: int = 24) -> pd.DataFrame:
    """Volume by price bucket over the given window (typical price). POC = max-volume bucket."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    edges = np.linspace(df["low"].min(), df["high"].max(), bins + 1)
    idx = np.clip(np.digitize(tp, edges) - 1, 0, bins - 1)
    vol = np.bincount(idx, weights=df["volume"].to_numpy(), minlength=bins)
    out = pd.DataFrame({"price_lo": edges[:-1], "price_hi": edges[1:], "volume": vol})
    out["poc"] = out["volume"] == out["volume"].max()
    return out
