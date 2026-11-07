"""Market structure, defined so nothing repaints.

A swing high at bar j is a bar whose high is strictly greater than the `left`
bars before it and greater than or equal to the `right` bars after it (so the
first of two equal highs is the pivot). It is only *known* at bar
j + right, so every column below is stamped on the confirmation bar, never on j.
`analyze(df.iloc[:k])` therefore equals `analyze(df).iloc[:k]` for every k;
tests/test_no_lookahead.py enforces that.

Definitions (all on bar close):
- HH/LH: a newly confirmed swing high above/below the previous confirmed one. HL/LL likewise.
- Bullish break: close crosses above the latest confirmed, unbroken swing high.
  It is a BOS when the prior structural trend was up or undefined, a CHoCH when it was down.
  Bearish breaks mirror this. A level breaks at most once.
- Liquidity sweep: the bar trades through the latest swing level but closes back inside it.
- Equal highs/lows: the last two confirmed swing highs (lows) within `eq_tol_atr` x ATR.
- FVG (3-bar): bullish when low[i] > high[i-2], zone [high[i-2], low[i]]; bearish mirrors.
- Order block: on a bullish break, the last down-close candle in the `ob_lookback` bars
  before the break; zone is its [low, high]. Bearish mirrors.
- Premium/discount: position of close in [last swing low, last swing high]; > 0.5 is premium.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import atr


def analyze(df: pd.DataFrame, left: int = 3, right: int = 3, eq_tol_atr: float = 0.15,
            ob_lookback: int = 10) -> pd.DataFrame:
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    a = atr(df, 14).to_numpy(float)
    n = len(df)
    nan = np.full(n, np.nan)
    cols = {k: nan.copy() for k in (
        "swing_high", "swing_low", "last_sh", "last_sl", "eqh", "eql",
        "fvg_bull_lo", "fvg_bull_hi", "fvg_bear_lo", "fvg_bear_hi",
        "ob_bull_lo", "ob_bull_hi", "ob_bear_lo", "ob_bear_hi", "range_pos")}
    sh_label = np.array([""] * n, dtype=object)
    sl_label = np.array([""] * n, dtype=object)
    brk = np.array([""] * n, dtype=object)   # BOS_UP, BOS_DN, CHOCH_UP, CHOCH_DN
    sweep = np.zeros(n, dtype=int)           # +1 bullish sweep (of lows), -1 bearish sweep (of highs)
    trend = np.zeros(n, dtype=int)

    last_sh = prev_sh = last_sl = prev_sl = np.nan
    sh_broken = sl_broken = True
    tr = 0
    for i in range(n):
        j = i - right
        if j - left >= 0:
            if h[j] > h[j - left:j].max() and h[j] >= h[j + 1:i + 1].max():
                prev_sh, last_sh, sh_broken = last_sh, h[j], False
                cols["swing_high"][i] = h[j]
                if not np.isnan(prev_sh):
                    sh_label[i] = "HH" if last_sh > prev_sh else "LH"
                    if not np.isnan(a[i]) and abs(last_sh - prev_sh) <= eq_tol_atr * a[i]:
                        cols["eqh"][i] = max(last_sh, prev_sh)
            if lo[j] < lo[j - left:j].min() and lo[j] <= lo[j + 1:i + 1].min():
                prev_sl, last_sl, sl_broken = last_sl, lo[j], False
                cols["swing_low"][i] = lo[j]
                if not np.isnan(prev_sl):
                    sl_label[i] = "HL" if last_sl > prev_sl else "LL"
                    if not np.isnan(a[i]) and abs(last_sl - prev_sl) <= eq_tol_atr * a[i]:
                        cols["eql"][i] = min(last_sl, prev_sl)

        if i > 0:
            if not sh_broken and not np.isnan(last_sh):
                if c[i] > last_sh:
                    brk[i] = "CHOCH_UP" if tr == -1 else "BOS_UP"
                    tr, sh_broken = 1, True
                    for k in range(i - 1, max(-1, i - 1 - ob_lookback), -1):
                        if c[k] < o[k]:
                            cols["ob_bull_lo"][i], cols["ob_bull_hi"][i] = lo[k], h[k]
                            break
                elif h[i] > last_sh:
                    sweep[i] = -1
            if not sl_broken and not np.isnan(last_sl) and brk[i] == "":
                if c[i] < last_sl:
                    brk[i] = "CHOCH_DN" if tr == 1 else "BOS_DN"
                    tr, sl_broken = -1, True
                    for k in range(i - 1, max(-1, i - 1 - ob_lookback), -1):
                        if c[k] > o[k]:
                            cols["ob_bear_lo"][i], cols["ob_bear_hi"][i] = lo[k], h[k]
                            break
                elif lo[i] < last_sl and sweep[i] == 0:
                    sweep[i] = 1
        if i >= 2:
            if lo[i] > h[i - 2]:
                cols["fvg_bull_lo"][i], cols["fvg_bull_hi"][i] = h[i - 2], lo[i]
            if h[i] < lo[i - 2]:
                cols["fvg_bear_lo"][i], cols["fvg_bear_hi"][i] = h[i], lo[i - 2]
        cols["last_sh"][i], cols["last_sl"][i] = last_sh, last_sl
        if not np.isnan(last_sh) and not np.isnan(last_sl) and last_sh > last_sl:
            cols["range_pos"][i] = (c[i] - last_sl) / (last_sh - last_sl)
        trend[i] = tr

    out = pd.DataFrame(cols, index=df.index)
    out["sh_label"] = sh_label
    out["sl_label"] = sl_label
    out["break"] = brk
    out["sweep"] = sweep
    out["structure_trend"] = trend
    return out


def zone(range_pos: float) -> str:
    if np.isnan(range_pos):
        return "unknown"
    return "premium" if range_pos > 0.5 else "discount"
