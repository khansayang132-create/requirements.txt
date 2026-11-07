import pandas as pd
import pytest
from pydantic import ValidationError

from promovent.config import Mode, RiskConfig, Settings
from promovent.models import Position, Signal
from promovent.risk import RiskEngine, RiskState, vol_scale

T = pd.Timestamp("2024-01-01", tz="UTC")


def sig(entry=100.0, stop=98.0, target=104.0, side=1, symbol="BTC/USDT"):
    return Signal("t", symbol, side, entry, stop, target, T)


def state(eq=10_000.0, **kw):
    return RiskState(eq, kw.pop("peak", eq), kw.pop("day", eq), kw.pop("week", eq), **kw)


def test_fixed_fraction_sizing():
    d = RiskEngine().evaluate(sig(), state())
    assert d.approved
    assert d.qty == pytest.approx(10_000 * 0.0025 / 2)  # 12.5 units, $25 risk (0.25 %)
    assert d.risk_amount == pytest.approx(25)


def test_notional_cap_means_no_leverage():
    d = RiskEngine().evaluate(sig(entry=100, stop=99.99, target=100.05), state())
    assert d.approved and d.qty * 100 <= 10_000 + 1e-6
    assert "notional" in d.reasons[0]


@pytest.mark.parametrize("kw,msg", [
    (dict(stop=101.0), "wrong side"),
    (dict(target=101.0), "reward/risk"),
    (dict(target=99.0), "target on the wrong side"),
])
def test_rejects_bad_geometry(kw, msg):
    d = RiskEngine().evaluate(sig(**kw), state())
    assert not d.approved and any(msg in r for r in d.reasons)


def test_daily_loss_lockout():
    d = RiskEngine().evaluate(sig(), state(9_790, day=10_000, week=10_000, peak=10_000))
    assert not d.approved and any("daily loss" in r for r in d.reasons)


def test_weekly_and_drawdown_lockouts():
    eng = RiskEngine()
    assert any("weekly" in r for r in eng.evaluate(sig(), state(9_590, day=9_590, week=10_000)).reasons)
    assert any("drawdown" in r for r in eng.evaluate(sig(), state(8_400, day=8_400, week=8_400, peak=10_000)).reasons)


def test_kill_switch_blocks():
    s = state()
    s.kill_switch, s.kill_reason = True, "test"
    assert not RiskEngine().evaluate(sig(), s).approved


def test_max_positions_and_duplicate_symbol():
    pos = [Position(f"X{i}/USDT", 1, 1, 100, 99, 103) for i in range(3)]
    assert any("max" in r for r in RiskEngine().evaluate(sig(), state(positions=pos)).reasons)
    one = [Position("BTC/USDT", 1, 1, 100, 99, 103)]
    assert any("already" in r for r in RiskEngine().evaluate(sig(), state(positions=one)).reasons)


def test_correlated_same_direction_blocked_opposite_allowed():
    pos = [Position("ETH/USDT", 1, 1, 100, 99.5, 103)]
    eng = RiskEngine()
    assert not eng.evaluate(sig(), state(positions=pos), {"ETH/USDT": 0.9}).approved
    hedge = sig(entry=100, stop=102, target=96, side=-1)
    assert eng.evaluate(hedge, state(positions=pos), {"ETH/USDT": 0.9}).approved


def test_portfolio_heat_caps_size():
    pos = [Position("ETH/USDT", 1, 130, 100, 99, 103)]  # $130 open risk of $150 max heat
    d = RiskEngine().evaluate(sig(), state(positions=pos))
    assert d.approved and d.risk_amount == pytest.approx(20)


def test_risk_never_increases_after_losses():
    eng = RiskEngine()
    fresh = eng.evaluate(sig(), state(10_000)).risk_amount
    after_dd = eng.evaluate(sig(), state(9_200, peak=10_000, day=9_200, week=9_200)).risk_amount
    assert after_dd < fresh * 9_200 / 10_000 + 1e-9  # halved by drawdown throttle


def test_vol_scale_only_shrinks():
    assert vol_scale(2.0, 1.0) == 0.5
    assert vol_scale(0.5, 1.0) == 1.0


@pytest.mark.parametrize("kw", [dict(martingale=True), dict(leverage=3.0), dict(risk_per_trade=0.05),
                                dict(daily_loss_limit=0.05, weekly_loss_limit=0.04)])
def test_config_hard_rules(kw):
    with pytest.raises(ValidationError):
        RiskConfig(**kw)


def test_defaults_match_spec():
    c = RiskConfig()
    assert (c.risk_per_trade, c.daily_loss_limit, c.weekly_loss_limit, c.max_concurrent_positions, c.leverage) == \
        (0.0025, 0.02, 0.03, 3, 1.0)


def test_live_mode_needs_explicit_switch():
    with pytest.raises(ValidationError):
        Settings(mode=Mode.AUTONOMOUS_LIVE)
    assert Settings(mode=Mode.ASSISTED_LIVE, live_trading_enabled=True).mode.is_live
