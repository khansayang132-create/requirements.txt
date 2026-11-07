"""Deterministic synthetic OHLCV for tests and the offline demo.

Clearly labeled: every frame carries attrs["source"] = "synthetic", and the API
and dashboard show a SYNTHETIC banner. Never presented as market data.
Regime-switching GBM: alternating trend / range / high-vol segments.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..models import TF_SECONDS, validate_ohlcv


def generate(n: int = 2000, tf: str = "1h", seed: int = 7, start_price: float = 30_000.0,
             start: str = "2024-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    seg = rng.integers(80, 250, size=n // 80 + 2)
    drifts, vols = [], []
    kinds = [(0.0012, 0.006), (-0.0010, 0.007), (0.0, 0.004), (0.0, 0.016), (0.0006, 0.005)]
    for length in seg:
        d, v = kinds[rng.integers(0, len(kinds))]
        drifts += [d] * int(length)
        vols += [v] * int(length)
    drifts, vols = np.array(drifts[:n]), np.array(vols[:n])
    rets = drifts + vols * rng.standard_normal(n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    wick = np.abs(rng.standard_normal((2, n))) * vols * close * 0.6
    high = np.maximum(open_, close) + wick[0]
    low = np.minimum(open_, close) - wick[1]
    vol = np.exp(rng.normal(3, 0.5, n)) * (1 + 40 * np.abs(rets))
    idx = pd.date_range(start, periods=n, freq=pd.Timedelta(seconds=TF_SECONDS[tf]), tz="UTC", name="time")
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)
    df = validate_ohlcv(df, tf)
    df.attrs["source"] = "synthetic"
    return df
