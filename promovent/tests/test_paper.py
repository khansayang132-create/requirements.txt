import pandas as pd
import pytest

from promovent.config import Mode, Settings
from promovent.models import Signal
from promovent.paper import ExecutionAgent, LiveTradingUnavailable, OrderRejected, PaperBroker
from promovent.risk import RiskEngine
from promovent.db import Store

T = pd.Timestamp("2024-01-01", tz="UTC")


def agent(mode=Mode.PAPER, validated=("t",), **kw):
    s = Settings(mode=mode, **kw)
    store = Store()
    return ExecutionAgent(s, RiskEngine(s.risk), PaperBroker(store), store, set(validated)), store


def sig(t=T, symbol="BTC/USDT"):
    return Signal("t", symbol, 1, 100, 98, 104, t)


def test_observation_and_signal_modes_never_order():
    for m in (Mode.OBSERVATION, Mode.SIGNAL):
        a, _ = agent(m)
        with pytest.raises(OrderRejected):
            a.execute(sig(), 100)


def test_live_refused_and_audited():
    a, store = agent(Mode.AUTONOMOUS_LIVE, live_trading_enabled=True)
    with pytest.raises(LiveTradingUnavailable):
        a.execute(sig(), 100)
    assert store.audit_log()[0]["action"] == "live_order_refused"


def test_unvalidated_strategy_refused():
    a, _ = agent(validated=())
    with pytest.raises(OrderRejected, match="validation"):
        a.execute(sig(), 100)


def test_fill_duplicate_and_stop_close():
    a, store = agent()
    r = a.execute(sig(), 100)
    assert r["qty"] > 0 and r["price"] > 100  # paid spread + slippage
    with pytest.raises(OrderRejected, match="duplicate"):
        a.execute(sig(), 100)
    closed = a.broker.on_price("BTC/USDT", 97.5)
    assert closed and closed[0]["reason"] == "stop" and closed[0]["pnl"] < 0
    assert len(store.positions("paper", closed=True)) == 1 and store.positions("paper") == []
    actions = [x["action"] for x in reversed(store.audit_log())]
    assert actions == ["risk_decision", "paper_fill"]


def test_kill_switch_blocks_orders():
    a, _ = agent()
    a.kill("tester", "drill")
    with pytest.raises(OrderRejected, match="kill switch"):
        a.execute(sig(), 100)


def test_partial_fill_recorded():
    a, store = agent()
    r = a.execute(sig(), 100, fill_ratio=0.4)
    assert not r["complete"]
    assert store.orders("paper")[0]["status"] == "partially_filled"


def test_migrations_idempotent(tmp_path):
    Store(str(tmp_path / "p.db"))
    s = Store(str(tmp_path / "p.db"))  # second run: alembic already at head, no error
    assert s.health()["ok"]
