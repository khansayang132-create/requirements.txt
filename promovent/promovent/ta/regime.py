"""Market regime classification (causal, bar-close).

Inputs: EMA50/EMA200 slope and separation, ADX(14), and realized volatility
percentile over a trailing window. Precedence:
  1. TRANSITION     EMA50 crossed EMA200 within the last `transition_bars`
  2. HIGH_VOL       vol percentile >= 0.9 (trend labels are unreliable then)
  3. STRONG_BULL / STRONG_BEAR   ADX >= 25 and price/EMA alignment
  4. WEAK_BULL / WEAK_BEAR       alignment with ADX in [18, 25)
  5. LOW_VOL        vol percentile <= 0.1
  6. SIDEWAYS       everything else
`tradeable` is False for HIGH_VOL and TRANSITION: the system's default is to stand aside.
"""
from __future__ import annotations

from enum import Enum

import numpy as np
import pandas as pd

from .indicators import adx, ema, realized_vol


class Regime(str, Enum):
    STRONG_BULL = "strong_bullish_trend"
    WEAK_BULL = "weak_bullish_trend"
    STRONG_BEAR = "strong_bearish_trend"
    WEAK_BEAR = "weak_bearish_trend"
    SIDEWAYS = "sideways"
    HIGH_VOL = "high_volatility"
    LOW_VOL = "low_volatility"
    TRANSITION = "transition"
    UNKNOWN = "unknown"


NOT_TRADEABLE = {Regime.HIGH_VOL, Regime.TRANSITION, Regime.UNKNOWN}


def classify(df: pd.DataFrame, vol_window: int = 50, pct_window: int = 300,
             transition_bars: int = 10) -> pd.DataFrame:
    c = df["close"]
    e50, e200 = ema(c, 50), ema(c, 200)
    ax = adx(df, 14)
    rv = realized_vol(c, vol_window)
    # trailing percentile of current vol within the last pct_window values (causal)
    pct = rv.rolling(pct_window, min_periods=min(100, pct_window)).apply(
        lambda w: (w[:-1] < w[-1]).mean() if len(w) > 1 else np.nan, raw=True)
    cross = np.sign(e50 - e200).diff().fillna(0).ne(0)
    recent_cross = cross.rolling(transition_bars, min_periods=1).max().astype(bool)
    slope = e50.diff(5)

    labels = []
    for i in range(len(df)):
        if np.isnan(e200.iloc[i]) or np.isnan(ax.iloc[i]) or np.isnan(pct.iloc[i]):
            labels.append(Regime.UNKNOWN)
            continue
        bull = c.iloc[i] > e50.iloc[i] > e200.iloc[i] and slope.iloc[i] > 0
        bear = c.iloc[i] < e50.iloc[i] < e200.iloc[i] and slope.iloc[i] < 0
        if recent_cross.iloc[i] and i > 200:
            labels.append(Regime.TRANSITION)
        elif pct.iloc[i] >= 0.9:
            labels.append(Regime.HIGH_VOL)
        elif bull and ax.iloc[i] >= 25:
            labels.append(Regime.STRONG_BULL)
        elif bear and ax.iloc[i] >= 25:
            labels.append(Regime.STRONG_BEAR)
        elif bull and ax.iloc[i] >= 18:
            labels.append(Regime.WEAK_BULL)
        elif bear and ax.iloc[i] >= 18:
            labels.append(Regime.WEAK_BEAR)
        elif pct.iloc[i] <= 0.1:
            labels.append(Regime.LOW_VOL)
        else:
            labels.append(Regime.SIDEWAYS)
    out = pd.DataFrame({"regime": [r.value for r in labels], "adx": ax, "vol_pct": pct}, index=df.index)
    out["tradeable"] = [r not in NOT_TRADEABLE for r in labels]
    return out
