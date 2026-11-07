from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd

from .features import FEATURES, build, label


@dataclass
class Dataset:
    X: pd.DataFrame
    y: pd.Series
    doc: dict

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        h.update(pd.util.hash_pandas_object(self.X, index=True).values.tobytes())
        h.update(pd.util.hash_pandas_object(self.y, index=True).values.tobytes())
        return h.hexdigest()[:16]


def prepare(frames: dict[str, pd.DataFrame], timeframe: str, horizon: int = 12, threshold: float = 0.0,
            source: str = "live") -> Dataset:
    """frames: {symbol: OHLCV}. Rows with any NaN feature or no label are dropped (warm-up and the tail)."""
    xs, ys, per = [], [], {}
    for sym, df in frames.items():
        X, y = build(df), label(df, horizon, threshold)
        ok = X.notna().all(axis=1) & y.notna()
        X, y = X[ok].copy(), y[ok]
        X.index = pd.MultiIndex.from_arrays([X.index, [sym] * len(X)], names=["time", "symbol"])
        y.index = X.index
        xs.append(X)
        ys.append(y)
        per[sym] = {"rows": int(ok.sum()), "start": str(df.index[0]), "end": str(df.index[-1]), "positive_rate": float(y.mean())}
    X = pd.concat(xs).sort_index(level="time")
    y = pd.concat(ys).loc[X.index]
    doc = {"source": source, "timeframe": timeframe, "horizon_bars": horizon, "threshold_log_return": threshold,
           "features": FEATURES, "symbols": per, "rows": int(len(X)),
           "label": f"1 if log(close[t+{horizon}]/close[t]) > {threshold}", "warmup": "rows with incomplete indicator history dropped"}
    return Dataset(X, y.astype(int), doc)


def purged_splits(times: pd.Index, n_folds: int, purge: int, min_train: float = 0.4):
    """Expanding-window chronological folds. `purge` bars are removed before each test block."""
    uniq = pd.Index(sorted(times.unique()))
    n = len(uniq)
    start = int(n * min_train)
    size = (n - start) // n_folds
    for k in range(n_folds):
        t0 = start + k * size
        t1 = n if k == n_folds - 1 else t0 + size
        train_end = uniq[max(0, t0 - purge) - 1]
        yield (times <= train_end), (times >= uniq[t0]) & (times <= uniq[t1 - 1])
