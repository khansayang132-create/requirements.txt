"""Multi-factor opportunity score (0-100). A RANKING, not a win probability.

Weights: trend 15, structure 15, volume 10, momentum 10, order flow 10,
liquidity 10, multi-timeframe 15, reward/risk 10, sentiment 5.
A factor whose data is missing scores 0 and is listed in `unavailable`:
missing data never earns points. Grade: A+ >= 90, A >= 80, B >= 70, else WATCHLIST.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .ta import indicators as ind
from .ta.structure import analyze

WEIGHTS = {"trend": 15, "structure": 15, "volume": 10, "momentum": 10, "order_flow": 10,
           "liquidity": 10, "multi_timeframe": 15, "reward_risk": 10, "sentiment": 5}
assert sum(WEIGHTS.values()) == 100


def grade(score: float) -> str:
    return "A+" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "WATCHLIST"


def _trend_dir(df: pd.DataFrame) -> int:
    c = df["close"]
    e50, e200 = ind.ema(c, 50).iloc[-1], ind.ema(c, 200).iloc[-1]
    if np.isnan(e200):
        e200 = ind.ema(c, min(100, len(c) // 2)).iloc[-1]
    if np.isnan(e50) or np.isnan(e200):
        return 0
    return 1 if c.iloc[-1] > e50 > e200 else -1 if c.iloc[-1] < e50 < e200 else 0


def score(df: pd.DataFrame, direction: int | None = None, htf: dict[str, pd.DataFrame] | None = None,
          reward_risk: float | None = None, book_metrics: dict | None = None, flow: dict | None = None,
          sentiment: dict | None = None, quote_volume_rank: float | None = None) -> dict:
    """`df` is the primary-timeframe frame (closed candles). `sentiment` may hold
    fear_greed (0-100) and/or funding_rate. `quote_volume_rank` in [0,1] across the universe."""
    if len(df) < 60:
        return {"score": 0.0, "grade": "WATCHLIST", "direction": 0, "components": {}, "unavailable": ["history<60 bars"]}
    c = df["close"]
    d = direction if direction in (1, -1) else _trend_dir(df)
    comp, missing, evidence = {}, [], []
    if d == 0:
        return {"score": 0.0, "grade": "WATCHLIST", "direction": 0, "components": {k: 0.0 for k in WEIGHTS},
                "unavailable": [], "evidence": ["no directional bias: EMAs not aligned"]}

    # trend: EMA alignment + slope + ADX strength
    e20, e50 = ind.ema(c, 20), ind.ema(c, 50)
    ax = ind.adx(df).iloc[-1]
    t = 0.0
    t += 0.4 if np.sign(c.iloc[-1] - e50.iloc[-1]) == d else 0
    t += 0.3 if np.sign(e20.iloc[-1] - e20.iloc[-6]) == d else 0
    t += 0.3 * min(1.0, max(0.0, (ax - 15) / 20)) if not np.isnan(ax) else 0
    comp["trend"] = t
    evidence.append(f"ADX {ax:.1f}" if not np.isnan(ax) else "ADX n/a")

    # structure: structural trend, recent break in direction, discount/premium
    st = analyze(df)
    s = 0.0
    s += 0.4 if st["structure_trend"].iloc[-1] == d else 0
    recent = st["break"].iloc[-30:]
    if (recent.str.endswith("_UP") if d == 1 else recent.str.endswith("_DN")).any():
        s += 0.3
    rp = st["range_pos"].iloc[-1]
    if not np.isnan(rp):
        s += 0.3 * (1 - rp if d == 1 else rp)
    comp["structure"] = s

    vz = ind.volume_zscore(df["volume"]).iloc[-5:].mean()
    comp["volume"] = float(np.clip((vz + 0.5) / 2, 0, 1)) if not np.isnan(vz) else 0.0

    r = ind.rsi(c).iloc[-1]
    hist = ind.macd(c)["hist"]
    m = 0.0
    if not np.isnan(r):
        m += 0.5 if (d == 1 and 50 < r < 75) or (d == -1 and 25 < r < 50) else 0
    if not np.isnan(hist.iloc[-1]):
        m += 0.25 if np.sign(hist.iloc[-1]) == d else 0
        m += 0.25 if np.sign(hist.iloc[-1] - hist.iloc[-2]) == d else 0
    comp["momentum"] = m
    evidence.append(f"RSI {r:.1f}" if not np.isnan(r) else "RSI n/a")

    if flow and flow.get("available"):
        ar = flow["aggressor_ratio"]
        of = (ar - 0.5) * 2 * d
        if book_metrics:
            of = 0.6 * of + 0.4 * book_metrics["imbalance"] * d
        comp["order_flow"] = float(np.clip(0.5 + of, 0, 1))
    else:
        comp["order_flow"] = 0.0
        missing.append("order_flow")

    if book_metrics or quote_volume_rank is not None:
        liq = []
        if book_metrics:
            liq.append(float(np.clip(1 - book_metrics["spread_bps"] / 10, 0, 1)))
        if quote_volume_rank is not None:
            liq.append(float(np.clip(quote_volume_rank, 0, 1)))
        comp["liquidity"] = float(np.mean(liq))
    else:
        comp["liquidity"] = 0.0
        missing.append("liquidity")

    if htf:
        agree = [1.0 if _trend_dir(f) == d else 0.0 for f in htf.values() if len(f) >= 60]
        comp["multi_timeframe"] = float(np.mean(agree)) if agree else 0.0
        if not agree:
            missing.append("multi_timeframe")
    else:
        comp["multi_timeframe"] = 0.0
        missing.append("multi_timeframe")

    if reward_risk is not None:
        comp["reward_risk"] = float(np.clip((reward_risk - 1) / 2, 0, 1))
    else:
        comp["reward_risk"] = 0.0
        missing.append("reward_risk")

    if sentiment:
        parts = []
        if "fear_greed" in sentiment:  # contrarian at extremes, aligned otherwise
            fg = sentiment["fear_greed"]
            parts.append(1.0 if (d == 1 and fg < 25) or (d == -1 and fg > 75) else 0.5)
        if "funding_rate" in sentiment:  # crowded side penalised
            fr = sentiment["funding_rate"]
            parts.append(0.2 if np.sign(fr) == d and abs(fr) > 0.0005 else 0.7)
        comp["sentiment"] = float(np.mean(parts)) if parts else 0.0
    else:
        comp["sentiment"] = 0.0
        missing.append("sentiment")

    pts = {k: round(comp[k] * w, 2) for k, w in WEIGHTS.items()}
    total = round(sum(pts.values()), 1)
    return {"score": total, "grade": grade(total), "direction": d, "components": pts, "unavailable": missing,
            "evidence": evidence, "note": "ranking score, not a probability of winning"}
