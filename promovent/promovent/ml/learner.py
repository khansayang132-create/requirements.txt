"""Continuous learning loop (worker job).

- retrain():   rebuild the live dataset, train every model kind with purged walk-forward, and PROMOTE the
               best only if its out-of-sample Brier beats the base rate. Otherwise nothing is promoted.
- predict():   log a prediction per symbol on each new closed bar with the promoted model.
- resolve():   once `horizon` bars have passed, record what actually happened.
- monitor():   compare live accuracy with validation; flag deterioration and recommend retraining.
Models never change trading rules: their output is shown, logged and evaluated only.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select

from ..db.models import Prediction, utcnow
from ..models import TF_SECONDS
from .dataset import prepare
from .train import KINDS, list_models, predict as model_predict, train


def retrain(app, symbols: list[str], tf: str = "1h", bars: int = 3000, horizon: int = 12, model_dir=None) -> dict:
    frames = {s: app.market.ohlcv(s, tf, bars)[0] for s in symbols}
    source = app.market.ohlcv(symbols[0], tf, 60)[1].source
    ds = prepare(frames, tf, horizon, source=source)
    results = []
    for kind in KINDS:
        m = train(ds, kind, model_dir, n_folds=4)
        v = m["validation"]
        results.append({"version": m["version"], "kind": kind, "auc": v["mean_auc"], "brier": v["mean_brier"],
                        "baseline_brier": v["mean_baseline_brier"], "beats_baseline": v["beats_baseline"]})
    eligible = [r for r in results if r["beats_baseline"] and source == "live"]
    best = min(eligible, key=lambda r: r["brier"]) if eligible else None
    app.store.kv_set("ml_promoted", best)
    return {"source": source, "rows": ds.doc["rows"], "results": results, "promoted": best,
            "note": None if best else "no model beat the base rate out of sample; nothing promoted"}


def predict(app, symbols: list[str], tf: str = "1h", model_dir=None) -> list[dict]:
    best = app.store.kv_get("ml_promoted")
    if not best:
        return []
    out = []
    for s in symbols:
        df, meta = app.market.ohlcv(s, tf, 600)
        p = model_predict(best["version"], df, meta.source, model_dir)
        bar = df.index[-1]
        with app.store.session() as sess:
            exists = sess.scalar(select(Prediction).where(Prediction.model_version == best["version"], Prediction.symbol == s,
                                                          Prediction.timeframe == tf, Prediction.bar_time == bar.to_pydatetime()))
            if exists:
                continue
            sess.add(Prediction(model_version=best["version"], symbol=s, timeframe=tf, bar_time=bar.to_pydatetime(),
                                horizon_bars=p["horizon_bars"], probability_up=p["probability_up"], price_at_bar=float(df["close"].iloc[-1]),
                                resolve_after=(bar + timedelta(seconds=TF_SECONDS[tf] * (p["horizon_bars"] + 1))).to_pydatetime()))
        out.append({"symbol": s, **p})
    return out


def resolve(app) -> int:
    now = utcnow()
    n = 0
    with app.store.session() as sess:
        rows = sess.scalars(select(Prediction).where(Prediction.resolved_at.is_(None))).all()
        pending = [(r.id, r.symbol, r.timeframe, r.bar_time, r.horizon_bars, r.price_at_bar, r.resolve_after) for r in rows]
    for pid, sym, tf, bar, h, px, after in pending:
        after = after if after.tzinfo else after.replace(tzinfo=now.tzinfo)
        if after > now:
            continue
        df, _ = app.market.ohlcv(sym, tf, 600)
        bar = pd.Timestamp(bar, tz="UTC") if bar.tzinfo is None else pd.Timestamp(bar)
        if bar not in df.index:
            continue
        i = df.index.get_loc(bar)
        if i + h >= len(df):
            continue
        up = bool(df["close"].iloc[i + h] > px)
        with app.store.session() as sess:
            r = sess.get(Prediction, pid)
            r.outcome_up, r.resolved_at = up, now
        n += 1
    return n


def monitor(app, min_resolved: int = 50) -> dict:
    with app.store.session() as sess:
        rows = sess.scalars(select(Prediction).where(Prediction.resolved_at.is_not(None))).all()
        data = [(r.model_version, r.probability_up, r.outcome_up) for r in rows]
    best = app.store.kv_get("ml_promoted")
    if not data:
        return {"status": "no resolved predictions yet", "promoted": best}
    df = pd.DataFrame(data, columns=["v", "p", "y"])
    if best:
        df = df[df.v == best["version"]]
    y, p = df.y.astype(float).to_numpy(), df.p.to_numpy()
    brier = float(np.mean((p - y) ** 2)) if len(y) else None
    base = float(np.mean((y.mean() - y) ** 2)) if len(y) else None
    out = {"resolved": len(y), "live_brier": brier, "live_baseline_brier": base,
           "live_hit_rate": float(np.mean((p >= 0.5) == (y == 1))) if len(y) else None,
           "validation_brier": best["brier"] if best else None, "promoted": best}
    if len(y) < min_resolved:
        out["status"] = f"collecting ({len(y)}/{min_resolved} resolved)"
    elif brier is not None and base is not None and brier > base:
        out["status"] = "deteriorated: live predictions worse than the base rate; demote and retrain"
        app.store.kv_set("ml_promoted", None)
        app.store.risk_event("model_deteriorated", "warn", out)
    elif best and brier > best["brier"] * 1.1:
        out["status"] = "degrading: live Brier >10% worse than validation; retrain recommended"
    else:
        out["status"] = "healthy"
    return out


__all__ = ["retrain", "predict", "resolve", "monitor", "list_models"]
