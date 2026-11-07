"""Market service, scanner, alerts and the rule-based trading copilot.

The copilot is deterministic: it explains what the indicators, structure and
score say, with supporting and conflicting evidence, an invalidation level and
the data timestamp. It does not call an LLM and does not predict.
When data cannot be fetched it says so; there is no silent fallback to
synthetic data. Synthetic data is only used when the caller asks for it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import synthetic
from .data.exchanges import ExchangeError, get_adapter
from .models import DEFAULT_UNIVERSE, MarketMeta, TF_SECONDS, validate_symbol, validate_timeframe
from .scoring import _trend_dir, score
from .strategies import REGISTRY
from .ta import indicators as ind
from .ta.regime import classify
from .ta.structure import analyze, zone


class DataUnavailable(RuntimeError):
    pass


@dataclass
class MarketService:
    source: str = "live"          # "live" or "synthetic"
    exchange: str = "binance"
    cache_seconds: float = 20.0
    _cache: dict = field(default_factory=dict)

    def ohlcv(self, symbol: str, tf: str, limit: int = 600) -> tuple[pd.DataFrame, MarketMeta]:
        symbol, tf = validate_symbol(symbol), validate_timeframe(tf)
        key = (symbol, tf, limit)
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self.cache_seconds:
            return hit[1], hit[2]
        if self.source == "synthetic":
            # one fixed-length series per symbol/timeframe, sliced, so every panel sees the same bars
            seed = sum(map(ord, symbol + tf))
            df = synthetic.generate(max(limit, 1500), tf, seed=seed, start_price=100 + seed * 7).iloc[-limit:]
            last = int(df.index[-1].value // 10**6) + TF_SECONDS[tf] * 1000
            meta = MarketMeta("synthetic", symbol, last, last, source="synthetic")
        else:
            try:
                r = get_adapter(self.exchange).ohlcv(symbol, tf, limit)
            except ExchangeError as e:
                raise DataUnavailable(str(e)) from e
            df, meta = r.df, r.meta
        self._cache[key] = (time.time(), df, meta)
        return df, meta

    def analysis(self, symbol: str, tf: str = "1h", htfs: tuple[str, ...] = ("4h", "1d")) -> dict:
        df, meta = self.ohlcv(symbol, tf)
        htf = {}
        for h in htfs:
            try:
                htf[h] = self.ohlcv(symbol, h, 300)[0]
            except DataUnavailable:
                pass
        reg = classify(df).iloc[-1]
        st = analyze(df)
        last = st.iloc[-1]
        a = float(ind.atr(df).iloc[-1])
        c = float(df["close"].iloc[-1])
        sc = score(df, htf=htf or None, reward_risk=2.0)
        d = sc["direction"]
        support, conflict = [], []
        if d:
            (support if last["structure_trend"] == d else conflict).append(
                f"structure trend {'up' if last['structure_trend'] == 1 else 'down' if last['structure_trend'] == -1 else 'undefined'}")
            for h, f in htf.items():
                hd = _trend_dir(f)
                (support if hd == d else conflict).append(f"{h} trend {'up' if hd == 1 else 'down' if hd == -1 else 'flat'}")
        r = float(ind.rsi(df["close"]).iloc[-1])
        if d == 1 and r > 70 or d == -1 and r < 30:
            conflict.append(f"RSI {r:.0f} stretched")
        if not reg["tradeable"]:
            conflict.append(f"regime {reg['regime']}: system stands aside")
        inval = last["last_sl"] if d == 1 else last["last_sh"] if d == -1 else np.nan
        if np.isnan(inval):
            inval = c - 2 * a * d if d else np.nan
        entry = c
        tgt = entry + d * 2 * abs(entry - inval) if d and not np.isnan(inval) else np.nan
        rr = abs(tgt - entry) / abs(entry - inval) if d and not np.isnan(inval) and entry != inval else None
        action = "wait"
        if d and reg["tradeable"] and sc["score"] >= 70 and len(conflict) <= 1:
            action = "candidate entry (requires risk approval)"
        return {"symbol": symbol, "timeframe": tf, "meta": meta.as_dict(), "price": c,
                "regime": reg["regime"], "tradeable": bool(reg["tradeable"]),
                "bias": {1: "bullish", -1: "bearish", 0: "neutral"}[d], "score": sc,
                "zone": zone(last["range_pos"]), "last_swing_high": _f(last["last_sh"]), "last_swing_low": _f(last["last_sl"]),
                "last_break": next((b for b in reversed(st["break"].tolist()) if b), None),
                "atr": a, "rsi": r, "supporting": support, "conflicting": conflict,
                "potential_entry": entry if d else None, "invalidation": _f(inval), "target_2r": _f(tgt),
                "reward_risk": rr, "suggested_action": action,
                "higher_timeframes_available": sorted(htf)}

    def scan(self, symbols: list[str] | None = None, tf: str = "1h") -> dict:
        rows, errors = [], {}
        for s in symbols or DEFAULT_UNIVERSE:
            try:
                df, meta = self.ohlcv(s, tf)
            except DataUnavailable as e:
                errors[s] = str(e)
                continue
            sc = score(df, reward_risk=2.0)
            st = analyze(df).iloc[-1]
            vz = float(ind.volume_zscore(df["volume"]).iloc[-1])
            sigs = {}
            for name, strat in REGISTRY.items():
                if tf in strat.timeframes:
                    sg = strat.signals(df).iloc[-1]
                    if sg["side"]:
                        sigs[name] = {"side": int(sg["side"]), "stop": float(sg["stop"]), "target": float(sg["target"])}
            rows.append({"symbol": s, "price": float(df["close"].iloc[-1]), "score": sc["score"], "grade": sc["grade"],
                         "direction": sc["direction"], "regime": classify(df)["regime"].iloc[-1],
                         "volume_z": vz if not np.isnan(vz) else None, "break": st["break"] or None,
                         "sweep": int(st["sweep"]), "signals": sigs, "meta": meta.as_dict()})
        rows.sort(key=lambda r: r["score"], reverse=True)
        return {"timeframe": tf, "results": rows, "errors": errors,
                "bullish": [r for r in rows if r["direction"] == 1][:5],
                "bearish": [r for r in rows if r["direction"] == -1][:5],
                "volume_anomalies": [r["symbol"] for r in rows if (r["volume_z"] or 0) >= 3],
                "liquidity_events": [r["symbol"] for r in rows if r["sweep"]],
                "breakouts": [r["symbol"] for r in rows if r["break"]]}


def alerts_from_scan(scan: dict) -> list[dict]:
    out = []
    for r in scan["results"]:
        if r["grade"] == "A+":
            out.append({"kind": "a_plus_setup", "symbol": r["symbol"], "message": f"A+ setup score {r['score']}"})
        if r["break"]:
            out.append({"kind": "breakout", "symbol": r["symbol"], "message": f"structure break {r['break']}"})
        if r["sweep"]:
            out.append({"kind": "liquidity_sweep", "symbol": r["symbol"],
                        "message": "swept lows" if r["sweep"] == 1 else "swept highs"})
        if (r["volume_z"] or 0) >= 3:
            out.append({"kind": "volume_expansion", "symbol": r["symbol"], "message": f"volume z {r['volume_z']:.1f}"})
    for s, e in scan["errors"].items():
        out.append({"kind": "data_outage", "symbol": s, "message": e[:200]})
    return out


def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)
