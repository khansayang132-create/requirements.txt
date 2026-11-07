"""Every signal-producing function must give the same value at bar k whether or
not bars after k exist. This is the repaint / look-ahead guard."""
import numpy as np
import pandas as pd
import pytest

from promovent.data import synthetic
from promovent.strategies import REGISTRY
from promovent.ta.regime import classify
from promovent.ta.structure import analyze

DF = synthetic.generate(900, seed=11)
CUTS = [320, 451, 600, 777]


def _same(a: pd.DataFrame, b: pd.DataFrame):
    for col in a.columns:
        x, y = a[col], b[col]
        if not pd.api.types.is_numeric_dtype(x):
            assert (x.values == y.values).all(), col
        else:
            assert np.allclose(x.to_numpy(float), y.to_numpy(float), equal_nan=True, rtol=1e-9, atol=1e-9), col


@pytest.mark.parametrize("k", CUTS)
def test_structure_does_not_repaint(k):
    _same(analyze(DF.iloc[:k]), analyze(DF).iloc[:k])


@pytest.mark.parametrize("k", CUTS)
def test_regime_is_causal(k):
    _same(classify(DF.iloc[:k]), classify(DF).iloc[:k])


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_strategy_signals_are_causal(name):
    full = REGISTRY[name].signals(DF)
    for k in CUTS:
        _same(REGISTRY[name].signals(DF.iloc[:k]), full.iloc[:k])
