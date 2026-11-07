import numpy as np
import pandas as pd

from promovent.data import synthetic
from promovent.ta import indicators as ind


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(up).dropna().iloc[-1] == 100.0
    df = synthetic.generate(500)
    r = ind.rsi(df["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_ema_matches_definition():
    s = pd.Series([1.0, 2, 3, 4, 5, 6])
    e = ind.ema(s, 3)
    k = 2 / 4
    manual = [1.0]
    for x in s.iloc[1:]:
        manual.append(manual[-1] + k * (x - manual[-1]))
    assert np.allclose(e.iloc[2:], manual[2:])
    assert e.iloc[:2].isna().all()


def test_atr_and_tr_positive():
    df = synthetic.generate(300)
    assert (ind.true_range(df).dropna() >= 0).all()
    assert (ind.atr(df).dropna() > 0).all()


def test_vwap_constant_price_equals_price():
    idx = pd.date_range("2024-01-01", periods=48, freq="1h", tz="UTC")
    df = pd.DataFrame({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 5.0}, index=idx)
    assert np.allclose(ind.vwap(df), 10.0)


def test_fib_levels():
    f = ind.fib_levels(100, 200)
    assert f["0.000"] == 200 and f["1.000"] == 100 and abs(f["0.618"] - 138.2) < 1e-9


def test_volume_profile_sums_volume():
    df = synthetic.generate(400)
    vp = ind.volume_profile(df, 20)
    assert np.isclose(vp["volume"].sum(), df["volume"].sum())
    assert vp["poc"].sum() >= 1
