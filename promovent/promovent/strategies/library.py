from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..ta import indicators as ind
from ..ta.structure import analyze
from .base import Strategy


def _set(out, mask, side, stop, target, reason):
    m = mask.fillna(False).to_numpy(bool) & (out["side"].to_numpy() == 0)
    out.loc[m, "side"] = side
    out.loc[m, "stop"] = stop[m]
    out.loc[m, "target"] = target[m]
    out.loc[m, "reason"] = reason


@dataclass
class TrendFollowing(Strategy):
    name: str = "trend_following"
    params: dict = field(default_factory=lambda: {"fast": 20, "slow": 50, "trend": 200, "adx_min": 20,
                                                  "stop_atr": 2.0, "rr": 2.0})
    entry_rules: str = "EMA(fast) crosses EMA(slow) in the direction of EMA(trend); ADX >= adx_min."
    exit_rules: str = "Fixed target at rr x risk, or stop."
    stop_method: str = "stop_atr x ATR(14) from the signal close."
    failure_conditions: str = "Choppy sideways markets (whipsaw crosses); late entries after extended moves."
    suited_regimes: tuple = ("strong_bullish_trend", "weak_bullish_trend", "strong_bearish_trend", "weak_bearish_trend")
    timeframes: tuple = ("1h", "4h", "1d")

    def signals(self, df):
        p, out, c = self.params, self._empty(df), df["close"]
        f, s, t = ind.ema(c, p["fast"]), ind.ema(c, p["slow"]), ind.ema(c, p["trend"])
        a, ax = ind.atr(df), ind.adx(df)
        up = (f > s) & (f.shift() <= s.shift()) & (c > t) & (ax >= p["adx_min"])
        dn = (f < s) & (f.shift() >= s.shift()) & (c < t) & (ax >= p["adx_min"])
        d = (p["stop_atr"] * a).to_numpy()
        cv = c.to_numpy()
        _set(out, up, 1, cv - d, cv + p["rr"] * d, "ema cross up with trend")
        _set(out, dn, -1, cv + d, cv - p["rr"] * d, "ema cross down with trend")
        return out


@dataclass
class LiquiditySweepReversal(Strategy):
    name: str = "liquidity_sweep_reversal"
    params: dict = field(default_factory=lambda: {"buffer_atr": 0.2, "min_rr": 1.5})
    entry_rules: str = "Bar sweeps the last confirmed swing low (high) and closes back inside, in discount (premium)."
    exit_rules: str = "Target = opposite confirmed swing level; trade skipped if that gives < min_rr."
    stop_method: str = "Beyond the sweep bar's extreme plus buffer_atr x ATR."
    failure_conditions: str = "Strong trends where sweeps become breakouts; thin books where wicks are noise."
    suited_regimes: tuple = ("sideways", "weak_bullish_trend", "weak_bearish_trend", "low_volatility")
    timeframes: tuple = ("15m", "1h", "4h")

    def signals(self, df):
        p, out = self.params, self._empty(df)
        st, a = analyze(df), ind.atr(df).to_numpy()
        c, h, lo = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
        stop_l = lo - p["buffer_atr"] * a
        stop_s = h + p["buffer_atr"] * a
        tgt_l, tgt_s = st["last_sh"].to_numpy(), st["last_sl"].to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            rr_l = (tgt_l - c) / (c - stop_l)
            rr_s = (c - tgt_s) / (stop_s - c)
        long_m = (st["sweep"] == 1) & (st["range_pos"] < 0.5) & pd.Series(rr_l >= p["min_rr"], index=df.index)
        short_m = (st["sweep"] == -1) & (st["range_pos"] > 0.5) & pd.Series(rr_s >= p["min_rr"], index=df.index)
        _set(out, long_m, 1, stop_l, tgt_l, "swept lows, closed back inside (discount)")
        _set(out, short_m, -1, stop_s, tgt_s, "swept highs, closed back inside (premium)")
        return out


@dataclass
class BreakoutRetest(Strategy):
    name: str = "breakout_retest"
    params: dict = field(default_factory=lambda: {"window": 12, "tol_atr": 0.25, "stop_atr": 1.0, "rr": 2.0})
    entry_rules: str = "After a BOS, price returns to the broken level within `window` bars (within tol_atr) and closes on the breakout side."
    exit_rules: str = "Target rr x risk."
    stop_method: str = "Broken level minus stop_atr x ATR (long)."
    failure_conditions: str = "Failed breakouts that close back through the level; news-driven spikes."
    suited_regimes: tuple = ("strong_bullish_trend", "weak_bullish_trend", "strong_bearish_trend", "weak_bearish_trend")
    timeframes: tuple = ("15m", "1h", "4h")

    def signals(self, df):
        p, out = self.params, self._empty(df)
        st, a = analyze(df), ind.atr(df).to_numpy()
        c, h, lo = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
        lsh, lsl = st["last_sh"].shift().to_numpy(), st["last_sl"].shift().to_numpy()
        brk = st["break"].to_numpy()
        lvl, side, age = np.nan, 0, 0
        for i in range(len(df)):
            if brk[i] in ("BOS_UP", "CHOCH_UP"):
                lvl, side, age = lsh[i], 1, 0
                continue
            if brk[i] in ("BOS_DN", "CHOCH_DN"):
                lvl, side, age = lsl[i], -1, 0
                continue
            if side == 0 or np.isnan(lvl) or np.isnan(a[i]):
                continue
            age += 1
            if age > p["window"]:
                side = 0
                continue
            tol = p["tol_atr"] * a[i]
            if side == 1 and lo[i] <= lvl + tol and c[i] > lvl:
                stop = lvl - p["stop_atr"] * a[i]
                out.iloc[i, :] = [1, stop, c[i] + p["rr"] * (c[i] - stop), "retest of broken high held"]
                side = 0
            elif side == -1 and h[i] >= lvl - tol and c[i] < lvl:
                stop = lvl + p["stop_atr"] * a[i]
                out.iloc[i, :] = [-1, stop, c[i] - p["rr"] * (stop - c[i]), "retest of broken low held"]
                side = 0
        out["side"] = out["side"].astype(int)
        return out


@dataclass
class VWAPMeanReversion(Strategy):
    name: str = "vwap_mean_reversion"
    params: dict = field(default_factory=lambda: {"n": 50, "z": 2.0, "rsi_lo": 30, "rsi_hi": 70,
                                                  "stop_atr": 1.5, "adx_max": 20})
    entry_rules: str = "Close deviates more than z std from rolling VWAP with RSI extreme, ADX below adx_max."
    exit_rules: str = "Target = rolling VWAP at signal time."
    stop_method: str = "stop_atr x ATR beyond the close."
    failure_conditions: str = "Trending markets: deviation keeps growing. Regime filter (ADX) is the guard."
    suited_regimes: tuple = ("sideways", "low_volatility")
    timeframes: tuple = ("5m", "15m", "1h")

    def signals(self, df):
        p, out, c = self.params, self._empty(df), df["close"]
        vw = ind.rolling_vwap(df, p["n"])
        dev = c - vw
        sd = dev.rolling(p["n"], min_periods=p["n"]).std(ddof=0)
        z = dev / sd.replace(0, np.nan)
        r, a, ax = ind.rsi(c), ind.atr(df).to_numpy(), ind.adx(df)
        cv, vv = c.to_numpy(), vw.to_numpy()
        quiet = ax < p["adx_max"]
        _set(out, (z < -p["z"]) & (r < p["rsi_lo"]) & quiet, 1, cv - p["stop_atr"] * a, vv, "stretched below VWAP")
        _set(out, (z > p["z"]) & (r > p["rsi_hi"]) & quiet, -1, cv + p["stop_atr"] * a, vv, "stretched above VWAP")
        return out


@dataclass
class MomentumContinuation(Strategy):
    name: str = "momentum_continuation"
    params: dict = field(default_factory=lambda: {"lookback": 20, "vol_z": 1.0, "stop_atr": 1.5, "rr": 2.0})
    entry_rules: str = "Close makes a `lookback`-bar high (low), MACD histogram rising (falling), RSI 55-75 (25-45), volume z-score >= vol_z."
    exit_rules: str = "Target rr x risk."
    stop_method: str = "stop_atr x ATR."
    failure_conditions: str = "Exhaustion tops; low-liquidity pumps."
    suited_regimes: tuple = ("strong_bullish_trend", "strong_bearish_trend")
    timeframes: tuple = ("15m", "1h", "4h")

    def signals(self, df):
        p, out, c = self.params, self._empty(df), df["close"]
        m, r, a = ind.macd(c), ind.rsi(c), ind.atr(df).to_numpy()
        vz = ind.volume_zscore(df["volume"])
        hi = c >= c.rolling(p["lookback"]).max()
        lo = c <= c.rolling(p["lookback"]).min()
        hist_up, hist_dn = m["hist"] > m["hist"].shift(), m["hist"] < m["hist"].shift()
        cv, d = c.to_numpy(), p["stop_atr"] * a
        _set(out, hi & hist_up & (m["hist"] > 0) & r.between(55, 75) & (vz >= p["vol_z"]), 1, cv - d, cv + p["rr"] * d,
             "momentum high with volume")
        _set(out, lo & hist_dn & (m["hist"] < 0) & r.between(25, 45) & (vz >= p["vol_z"]), -1, cv + d, cv - p["rr"] * d,
             "momentum low with volume")
        return out


@dataclass
class VolatilityExpansion(Strategy):
    name: str = "volatility_expansion"
    params: dict = field(default_factory=lambda: {"n": 20, "squeeze_pct": 0.15, "lookback": 120, "rr": 2.0})
    entry_rules: str = "Bollinger width on the prior bar in the lowest squeeze_pct of the last `lookback` bars; close breaks a band."
    exit_rules: str = "Target rr x risk."
    stop_method: str = "Middle band at signal time."
    failure_conditions: str = "False breakouts from the squeeze; very low volume."
    suited_regimes: tuple = ("low_volatility", "sideways")
    timeframes: tuple = ("15m", "1h", "4h")

    def signals(self, df):
        p, out, c = self.params, self._empty(df), df["close"]
        b = ind.bollinger(c, p["n"])
        w = b["width"]
        rank = w.rolling(p["lookback"], min_periods=p["lookback"]).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
        squeeze = rank.shift() <= p["squeeze_pct"]
        cv, mid = c.to_numpy(), b["mid"].to_numpy()
        _set(out, squeeze & (c > b["upper"]), 1, mid, cv + p["rr"] * (cv - mid), "squeeze break up")
        _set(out, squeeze & (c < b["lower"]), -1, mid, cv - p["rr"] * (mid - cv), "squeeze break down")
        return out


@dataclass
class MarketStructureOB(Strategy):
    name: str = "market_structure"
    params: dict = field(default_factory=lambda: {"rr": 2.0, "buffer_atr": 0.1, "max_risk_atr": 3.0})
    entry_rules: str = "On a bullish (bearish) BOS/CHoCH that leaves an order block, enter at close."
    exit_rules: str = "Target rr x risk."
    stop_method: str = "Beyond the order block plus buffer_atr x ATR; skipped if wider than max_risk_atr x ATR."
    failure_conditions: str = "Ranging markets producing alternating breaks; OBs far from price."
    suited_regimes: tuple = ("strong_bullish_trend", "weak_bullish_trend", "strong_bearish_trend", "weak_bearish_trend", "transition")
    timeframes: tuple = ("1h", "4h", "1d")

    def signals(self, df):
        p, out = self.params, self._empty(df)
        st, a = analyze(df), ind.atr(df).to_numpy()
        c = df["close"].to_numpy()
        sl_l = st["ob_bull_lo"].to_numpy() - p["buffer_atr"] * a
        sl_s = st["ob_bear_hi"].to_numpy() + p["buffer_atr"] * a
        ok_l = pd.Series((c - sl_l) <= p["max_risk_atr"] * a, index=df.index)
        ok_s = pd.Series((sl_s - c) <= p["max_risk_atr"] * a, index=df.index)
        _set(out, st["break"].str.endswith("_UP") & st["ob_bull_lo"].notna() & ok_l, 1, sl_l, c + p["rr"] * (c - sl_l),
             "bullish break with order block")
        _set(out, st["break"].str.endswith("_DN") & st["ob_bear_hi"].notna() & ok_s, -1, sl_s, c - p["rr"] * (sl_s - c),
             "bearish break with order block")
        return out


def _swing() -> Strategy:
    s = TrendFollowing(params={"fast": 20, "slow": 50, "trend": 200, "adx_min": 18, "stop_atr": 2.5, "rr": 2.5})
    s.name, s.timeframes = "swing_trading", ("4h", "1d")
    s.entry_rules = "Trend-following rules on 4h/1D with wider stops (variant of trend_following)."
    return s


def _scalp() -> Strategy:
    s = VWAPMeanReversion(params={"n": 30, "z": 2.2, "rsi_lo": 25, "rsi_hi": 75, "stop_atr": 1.0, "adx_max": 18})
    s.name, s.timeframes = "intraday_scalping", ("1m", "3m", "5m")
    s.entry_rules = "VWAP mean-reversion rules with tighter parameters on 1-5m (variant of vwap_mean_reversion)."
    s.failure_conditions += " Fees and spread dominate on 1m: requires low-fee venue; check cost model."
    return s


REGISTRY = {s.name: s for s in [TrendFollowing(), LiquiditySweepReversal(), BreakoutRetest(), VWAPMeanReversion(),
                                MomentumContinuation(), VolatilityExpansion(), MarketStructureOB(), _swing(), _scalp()]}


def get_strategy(name: str, params: dict | None = None) -> Strategy:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; one of {sorted(REGISTRY)}")
    base = REGISTRY[name]
    s = type(base)(params={**base.params, **(params or {})})
    for k in ("name", "entry_rules", "timeframes", "failure_conditions"):
        setattr(s, k, getattr(base, k))
    return s
