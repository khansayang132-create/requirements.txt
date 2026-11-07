from __future__ import annotations

import numpy as np
import pandas as pd

from ..ta import indicators as ind

FEATURES = ["ret_1", "ret_4", "ret_12", "ret_48", "rsi_14", "macd_hist_n", "atr_n", "bb_width", "bb_pos", "ema20_dist",
            "ema50_dist", "ema200_dist", "adx_14", "vol_z", "rvol_48", "hour_sin", "hour_cos"]


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Causal feature matrix (row i uses bars <= i). Scale-free so models transfer across symbols."""
    c = df["close"]
    a = ind.atr(df)
    bb = ind.bollinger(c)
    out = pd.DataFrame(index=df.index)
    lc = np.log(c)
    for n in (1, 4, 12, 48):
        out[f"ret_{n}"] = lc.diff(n)
    out["rsi_14"] = ind.rsi(c) / 100
    out["macd_hist_n"] = ind.macd(c)["hist"] / c
    out["atr_n"] = a / c
    out["bb_width"] = bb["width"]
    out["bb_pos"] = (c - bb["lower"]) / (bb["upper"] - bb["lower"]).replace(0, np.nan)
    for n in (20, 50, 200):
        out[f"ema{n}_dist"] = c / ind.ema(c, n) - 1
    out["adx_14"] = ind.adx(df) / 100
    out["vol_z"] = ind.volume_zscore(df["volume"])
    out["rvol_48"] = ind.realized_vol(c, 48)
    h = df.index.hour
    out["hour_sin"], out["hour_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    return out[FEATURES]


def label(df: pd.DataFrame, horizon: int, threshold: float) -> pd.Series:
    """1 if log return from close[i] to close[i+horizon] > threshold. NaN for the last `horizon` rows."""
    fwd = np.log(df["close"]).shift(-horizon) - np.log(df["close"])
    y = (fwd > threshold).astype(float)
    y[fwd.isna()] = np.nan
    return y
