"""Strategies G and I as research analytics (no automated trading yet; see STATUS.md)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def pair_spread_zscore(a: pd.Series, b: pd.Series, window: int = 200) -> pd.DataFrame:
    """G: rolling-OLS hedge ratio on log prices, spread z-score. Causal (rolling windows only)."""
    la, lb = np.log(a), np.log(b)
    cov = la.rolling(window).cov(lb)
    var = lb.rolling(window).var()
    beta = cov / var
    spread = la - beta * lb
    z = (spread - spread.rolling(window).mean()) / spread.rolling(window).std()
    corr = la.diff().rolling(window).corr(lb.diff())
    return pd.DataFrame({"beta": beta, "spread": spread, "z": z, "return_corr": corr})


def funding_basis(funding_rate: float, mark: float | None, spot: float | None,
                  periods_per_day: int = 3, extreme: float = 0.0005) -> dict:
    """I: annualized funding and perp-spot basis. `extreme` = 0.05 % per 8h by default."""
    out = {"funding_rate": funding_rate, "annualized_pct": funding_rate * periods_per_day * 365 * 100,
           "extreme": abs(funding_rate) >= extreme,
           "crowding": "longs paying" if funding_rate > 0 else "shorts paying" if funding_rate < 0 else "flat"}
    if mark and spot:
        out["basis_bps"] = (mark - spot) / spot * 1e4
    return out
