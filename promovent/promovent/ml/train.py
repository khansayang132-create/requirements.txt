"""Training, evaluation, versioned registry, prediction and drift monitoring."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score

from .dataset import Dataset, purged_splits
from .features import FEATURES, build

MODEL_DIR = Path(os.getenv("PROMOVENT_MODEL_DIR", "models"))


def make(kind: str, seed: int = 7):
    if kind == "lightgbm":
        return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=50,
                                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=seed, verbose=-1)
    if kind == "random_forest":
        return RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=50, n_jobs=-1, random_state=seed)
    if kind == "xgboost":
        from xgboost import XGBClassifier
        return XGBClassifier(n_estimators=300, learning_rate=0.03, max_depth=4, min_child_weight=20, subsample=0.8,
                             colsample_bytree=0.8, reg_lambda=1.0, random_state=seed, n_jobs=2, eval_metric="logloss")
    if kind == "statistical":
        # Statistical forecasting baseline: regularised logistic regression on standardised lagged returns,
        # volatility and RSI (a linear AR-style model). Trees must beat this to be worth their complexity.
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=500))
    raise ValueError(kind)


KINDS = ("lightgbm", "xgboost", "random_forest", "statistical")


def _metrics(y, p) -> dict:
    out = {"n": int(len(y)), "positive_rate": float(np.mean(y)), "accuracy": float(accuracy_score(y, p >= 0.5)),
           "brier": float(brier_score_loss(y, p)), "baseline_brier": float(brier_score_loss(y, np.full(len(y), np.mean(y))))}
    out["auc"] = float(roc_auc_score(y, p)) if len(set(y)) > 1 else None
    top = p >= np.quantile(p, 0.8)
    out["precision_top20pct"] = float(np.mean(np.asarray(y)[top])) if top.any() else None
    return out


def evaluate(ds: Dataset, kind: str, n_folds: int = 4) -> dict:
    times = ds.X.index.get_level_values("time")
    folds = []
    for tr, te in purged_splits(times, n_folds, purge=ds.doc["horizon_bars"]):
        m = make(kind).fit(ds.X[tr], ds.y[tr])
        p = m.predict_proba(ds.X[te])[:, 1]
        r = _metrics(ds.y[te].to_numpy(), p)
        r.update(train_end=str(times[tr].max()), test_start=str(times[te].min()), test_end=str(times[te].max()))
        folds.append(r)
    aucs = [f["auc"] for f in folds if f["auc"] is not None]
    return {"method": f"expanding walk-forward, {n_folds} folds, purge {ds.doc['horizon_bars']} bars, no shuffling",
            "folds": folds, "mean_auc": float(np.mean(aucs)) if aucs else None,
            "mean_brier": float(np.mean([f["brier"] for f in folds])),
            "mean_baseline_brier": float(np.mean([f["baseline_brier"] for f in folds])),
            "beats_baseline": float(np.mean([f["brier"] for f in folds])) < float(np.mean([f["baseline_brier"] for f in folds]))}


def train(ds: Dataset, kind: str = "lightgbm", model_dir: Path | None = None, n_folds: int = 4) -> dict:
    model_dir = Path(model_dir or MODEL_DIR)
    ev = evaluate(ds, kind, n_folds)
    model = make(kind).fit(ds.X, ds.y)
    imp = getattr(model, "feature_importances_", None)
    if imp is None and hasattr(model, "steps"):
        imp = np.abs(model.steps[-1][1].coef_[0])
    imp = imp if imp is not None else np.zeros(len(FEATURES))
    version = f"{kind[:3]}-{ds.fingerprint()}-{int(time.time())}"
    meta = {"version": version, "kind": kind, "trained_at": datetime.now(timezone.utc).isoformat(), "dataset": ds.doc,
            "dataset_fingerprint": ds.fingerprint(), "validation": ev,
            "feature_importance": dict(sorted(zip(FEATURES, map(float, imp), strict=True), key=lambda kv: -kv[1])),
            "training_distribution": {f: _hist(ds.X[f]) for f in FEATURES},
            "usage": "advisory input only; cannot approve, size or block trades"}
    d = model_dir / version
    d.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, d / "model.joblib")
    (d / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    return meta


def _hist(s: pd.Series, bins: int = 10) -> dict:
    edges = np.unique(np.quantile(s.dropna(), np.linspace(0, 1, bins + 1)))
    counts, _ = np.histogram(s.dropna(), bins=edges)
    return {"edges": edges.tolist(), "share": (counts / max(counts.sum(), 1)).tolist()}


def list_models(model_dir: Path | None = None) -> list[dict]:
    model_dir = Path(model_dir or MODEL_DIR)
    out = []
    for m in sorted(model_dir.glob("*/metadata.json"), reverse=True):
        meta = json.loads(m.read_text())
        out.append({k: meta[k] for k in ("version", "kind", "trained_at")} | {
            "source": meta["dataset"]["source"], "timeframe": meta["dataset"]["timeframe"], "rows": meta["dataset"]["rows"],
            "mean_auc": meta["validation"]["mean_auc"], "beats_baseline": meta["validation"]["beats_baseline"]})
    return out


def load(version: str, model_dir: Path | None = None):
    d = Path(model_dir or MODEL_DIR) / version
    if not (d / "metadata.json").exists():
        raise FileNotFoundError(f"model {version} not found")
    return joblib.load(d / "model.joblib"), json.loads((d / "metadata.json").read_text())


def predict(version: str, df: pd.DataFrame, data_source: str, model_dir: Path | None = None) -> dict:
    model, meta = load(version, model_dir)
    if meta["dataset"]["source"] != data_source and data_source == "live":
        warn = f"model trained on {meta['dataset']['source']} data; prediction on live data is not validated"
    else:
        warn = None
    X = build(df).iloc[[-1]]
    if X.isna().any(axis=1).iloc[0]:
        raise ValueError("not enough history for features")
    p = float(model.predict_proba(X)[:, 1][0])
    return {"version": version, "probability_up": p, "horizon_bars": meta["dataset"]["horizon_bars"],
            "bar_time": str(df.index[-1]), "predicted_at": datetime.now(timezone.utc).isoformat(), "data_source": data_source,
            "warning": warn, "drift": drift(meta, build(df).dropna().iloc[-500:])}


def psi(expected: list[float], actual: list[float]) -> float:
    e, a = np.clip(np.array(expected), 1e-6, None), np.clip(np.array(actual), 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


def drift(meta: dict, X_recent: pd.DataFrame) -> dict:
    """Population Stability Index per feature vs the training distribution. > 0.25 = major shift."""
    out = {}
    for f, h in meta["training_distribution"].items():
        if f not in X_recent or len(h["edges"]) < 2 or X_recent[f].dropna().empty:
            continue
        counts, _ = np.histogram(np.clip(X_recent[f].dropna(), h["edges"][0], h["edges"][-1]), bins=h["edges"])
        out[f] = round(psi(h["share"], counts / max(counts.sum(), 1)), 4)
    worst = max(out.values()) if out else 0.0
    return {"psi": out, "max_psi": worst, "status": "major_drift" if worst > 0.25 else "moderate_drift" if worst > 0.1 else "stable"}
