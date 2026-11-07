import numpy as np
import pandas as pd
import pytest

from promovent.backtest import Costs, ValidationGate, metrics, monte_carlo, run, walk_forward
from promovent.data import synthetic
from promovent.strategies import get_strategy
from promovent.strategies.base import Strategy

ZERO = Costs(0, 0, 0)


def frame(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx).astype(float)


class OneShot(Strategy):
    def __init__(self, at, side, stop, target):
        super().__init__(name="oneshot")
        self.at, self.side, self.stop, self.target = at, side, stop, target

    def signals(self, df):
        out = self._empty(df)
        if self.at < len(df):
            out.iloc[self.at] = [self.side, self.stop, self.target, "test"]
        return out


def test_fill_at_next_open_and_target():
    df = frame([[100, 101, 99, 100, 1], [102, 103, 101, 102, 1], [102, 110, 101, 109, 1], [109, 109, 108, 108, 1]])
    r = run(df, OneShot(0, 1, 98, 108), costs=ZERO)
    t = r.trades[0]
    assert t.entry == 102 and t.entry_time == df.index[1]   # next bar open, not signal close 100
    assert t.exit == 108 and t.exit_reason == "target"
    assert t.r_multiple == pytest.approx(1.5)


def test_risk_engine_rejects_low_reward_risk_in_backtest():
    df = frame([[100, 101, 99, 100, 1], [102, 103, 101, 102, 1], [102, 110, 101, 109, 1], [109, 109, 108, 108, 1]])
    assert run(df, OneShot(0, 1, 98, 106), costs=ZERO).trades == []  # 1.0R < min 1.5R


def test_stop_first_when_both_hit_same_bar():
    df = frame([[100, 100, 100, 100, 1], [100, 100, 100, 100, 1], [100, 120, 80, 100, 1]])
    r = run(df, OneShot(0, 1, 95, 110), costs=ZERO)
    assert r.trades[0].exit_reason == "stop" and r.trades[0].exit == 95


def test_gap_through_stop_fills_at_open():
    df = frame([[100, 100, 100, 100, 1], [100, 100, 100, 100, 1], [90, 91, 89, 90, 1]])
    r = run(df, OneShot(0, 1, 95, 110), costs=ZERO)
    assert r.trades[0].exit == 90


def test_signal_on_last_bar_is_never_filled():
    df = frame([[100, 100, 100, 100, 1]] * 5)
    assert run(df, OneShot(4, 1, 95, 110), costs=ZERO).trades == []


def test_costs_reduce_pnl():
    df = frame([[100, 101, 99, 100, 1], [102, 103, 101, 102, 1], [102, 110, 101, 109, 1], [109, 109, 108, 108, 1]])
    free = run(df, OneShot(0, 1, 98, 109), costs=ZERO).trades[0]
    paid = run(df, OneShot(0, 1, 98, 109), costs=Costs(10, 2, 3)).trades[0]
    assert paid.pnl < free.pnl and paid.fees > 0
    assert paid.entry == pytest.approx(102 * (1 + 4 / 1e4))


def test_equity_reconciles_with_trades():
    df = synthetic.generate(1500, seed=5)
    r = run(df, get_strategy("market_structure"))
    assert r.metrics["trades"] > 5
    assert r.equity.iloc[-1] == pytest.approx(10_000 + sum(t.pnl for t in r.trades), rel=1e-9)


def test_risk_per_trade_respected_in_backtest():
    df = synthetic.generate(1500, seed=5)
    r = run(df, get_strategy("market_structure"), costs=ZERO)
    stops = [t for t in r.trades if t.exit_reason == "stop"]
    # without costs a stop-out loses exactly 1R unless price gapped through the stop
    assert stops and np.median([t.r_multiple for t in stops]) == pytest.approx(-1.0)
    assert all(t.pnl <= 0 for t in stops)


def test_metrics_and_monte_carlo_shapes():
    df = synthetic.generate(2000, seed=8)
    r = run(df, get_strategy("market_structure"))
    for k in ("sharpe", "sortino", "calmar", "profit_factor", "expectancy", "max_consecutive_losses", "avg_holding_hours"):
        assert k in r.metrics
    mc = monte_carlo(r.trades, n=200)
    assert mc["final_equity_p05"] <= mc["final_equity_p50"] <= mc["final_equity_p95"]
    assert metrics([], pd.Series([1.0, 1.0], index=df.index[:2]), 1.0)["trades"] == 0


def test_walk_forward_and_gate():
    df = synthetic.generate(3000, seed=9)
    grid = [{"rr": 1.5}, {"rr": 2.0}, {"rr": 2.5}]
    wf = walk_forward(df, lambda p: get_strategy("market_structure", p), grid, n_folds=3)
    assert len(wf["folds"]) == 3 and all(f["params"] in grid for f in wf["folds"])
    gate = ValidationGate(min_trades=10_000).check({"trades": 3, "profit_factor": 0.5}, wf, {"runs": 0})
    assert not gate["passed"] and len(gate["failures"]) >= 2


def test_partial_fill_and_funding():
    df = frame([[100, 100, 100, 100, 1], [100, 100, 100, 100, 1], [100, 100, 100, 100, 1], [100, 120, 100, 120, 1]])
    full = run(df, OneShot(0, 1, 98, 110), costs=ZERO).trades[0]
    half = run(df, OneShot(0, 1, 98, 110), costs=Costs(0, 0, 0, fill_ratio=0.5)).trades[0]
    assert half.qty == pytest.approx(full.qty / 2)
    funded = run(df, OneShot(0, 1, 98, 110), costs=Costs(0, 0, 0, funding_rate_8h=0.001)).trades[0]
    assert funded.funding > 0 and funded.pnl < full.pnl
