import inspect

import numpy as np
import pytest

from promovent.data import synthetic
from promovent.ml import dataset, features, train
from promovent.risk import RiskEngine


def frames():
    return {s: synthetic.generate(1500, "1h", seed=i, start_price=100 + i) for i, s in enumerate(["AAA/USDT", "BBB/USDT"])}


def test_features_are_causal():
    df = synthetic.generate(800, seed=3)
    full = features.build(df)
    for k in (300, 555):
        part = features.build(df.iloc[:k])
        assert np.allclose(part.to_numpy(), full.iloc[:k].to_numpy(), equal_nan=True)


def test_label_uses_future_and_tail_dropped():
    df = synthetic.generate(300, seed=1)
    y = features.label(df, 5, 0.0)
    assert y.iloc[-5:].isna().all() and y.iloc[:-5].notna().all()
    assert y.iloc[10] == float(df["close"].iloc[15] > df["close"].iloc[10])


def test_purged_splits_never_overlap():
    ds = dataset.prepare(frames(), "1h", horizon=12, source="synthetic")
    t = ds.X.index.get_level_values("time")
    for tr, te in dataset.purged_splits(t, 4, purge=12):
        gap = (t[te].min() - t[tr].max()).total_seconds() / 3600
        assert gap > 12  # label window of the last training row ends before the first test row


def test_train_version_metadata_predict_drift(tmp_path):
    ds = dataset.prepare(frames(), "1h", horizon=12, source="synthetic")
    for kind in ("lightgbm", "random_forest"):
        meta = train.train(ds, kind, tmp_path, n_folds=3)
        assert meta["version"].startswith(kind[:3]) and meta["dataset"]["source"] == "synthetic"
        assert len(meta["validation"]["folds"]) == 3 and meta["validation"]["mean_auc"] is not None
        assert "advisory" in meta["usage"]
    listed = train.list_models(tmp_path)
    assert len(listed) == 2 and {m["source"] for m in listed} == {"synthetic"}
    df = synthetic.generate(600, seed=99)
    p = train.predict(listed[0]["version"], df, "live", tmp_path)
    assert 0 <= p["probability_up"] <= 1 and p["predicted_at"] and p["version"] == listed[0]["version"]
    assert "not validated" in p["warning"] and p["drift"]["status"] in ("stable", "moderate_drift", "major_drift")


def test_drift_detects_shift():
    meta = {"training_distribution": {"x": {"edges": [0, 1, 2, 3], "share": [1 / 3, 1 / 3, 1 / 3]}}}
    import pandas as pd
    assert train.drift(meta, pd.DataFrame({"x": np.full(300, 2.5)}))["status"] == "major_drift"
    assert train.drift(meta, pd.DataFrame({"x": np.linspace(0, 3, 300)}))["status"] == "stable"


def test_ml_cannot_influence_risk_engine():
    assert "probab" not in inspect.signature(RiskEngine.evaluate).parameters.__repr__()
    src = inspect.getsource(RiskEngine)
    assert "ml" not in src.lower().replace("html", "")


def test_missing_model():
    with pytest.raises(FileNotFoundError):
        train.load("nope")
