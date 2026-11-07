"""V3.0 / V3.1 behaviour: persistence, Risk Guardian, autopilot gates, opportunities, filters, reviews, reports,
research, learning loop, Binance client hardening."""
import time

import httpx
import pandas as pd
import pytest

from promovent.api import App
from promovent.autopilot import opportunity, review, universe
from promovent.autopilot.engine import Autopilot
from promovent.backtest import Costs
from promovent.config import Mode, RiskConfig, Settings
from promovent.data import synthetic
from promovent.db.models import Report, ResearchFinding, StrategyResearch
from promovent.execution.clients import BinanceTrading, Credentials, ExchangeUnavailable, Rules
from promovent.guardian import RESUME_PHRASE, RiskGuardian
from promovent.models import Signal
from promovent.paper import OrderRejected, PaperBroker
from promovent.risk import RiskEngine, RiskState

from .fake_exchanges import KEY, SECRET, FakeBinance

T = pd.Timestamp("2026-01-01", tz="UTC")


def app(tmp_path, **kw):
    return App(kw.pop("settings", Settings(mode=Mode.PAPER)), source="synthetic", db=f"sqlite:///{tmp_path}/a.db", keys={}, no_auth=True,
               redis_url="", **kw)


# ------------------------------------------------------------------ persistence and crash recovery
def test_paper_state_survives_restart(tmp_path):
    a = app(tmp_path)
    a.agent.validated.add("t")
    a.agent.execute(Signal("t", "BTC/USDT", 1, 100, 98, 106, T), 100)
    a.broker.set_kill(True, "drill")
    cash, pos = a.broker.cash, a.broker.state.positions[0]
    b = app(tmp_path)  # new process, same database
    assert b.broker.cash == pytest.approx(cash) and len(b.broker.state.positions) == 1
    p = b.broker.state.positions[0]
    assert (p.symbol, p.qty, p.stop, p.target) == (pos.symbol, pos.qty, pos.stop, pos.target)
    assert b.broker.state.kill_switch and b.broker.state.kill_reason == "drill"
    closed = b.broker.on_price("BTC/USDT", 97)  # restored position is still managed: stop fires
    assert closed and closed[0]["reason"] == "stop"
    assert app(tmp_path).broker.state.positions == []


def test_daily_baseline_rolls_and_persists(tmp_path):
    a = app(tmp_path)
    a.broker.roll(pd.Timestamp("2026-03-02 10:00", tz="UTC"))
    a.broker.cash = 9_900
    a.broker.roll(pd.Timestamp("2026-03-02 20:00", tz="UTC"))
    assert a.broker.state.day_start_equity == 10_000
    a.broker.roll(pd.Timestamp("2026-03-03 00:01", tz="UTC"))
    assert a.broker.state.day_start_equity == 9_900 and app(tmp_path).broker.state.day_start_equity == 9_900


# ------------------------------------------------------------------ V3.1 limits and Risk Guardian
def test_v31_limits_on_30_dollar_account():
    c = RiskConfig()
    assert (c.risk_per_trade, c.daily_loss_limit, c.max_drawdown, c.leverage) == (0.0025, 0.02, 0.02, 1.0)
    st = RiskState(30, 30, 30, 30, initial_equity=30)
    d = RiskEngine().evaluate(Signal("t", "BTC/USDT", 1, 100, 99, 103, T), st)
    assert d.risk_amount == pytest.approx(0.075)
    st.equity = 29.40  # -2 % = $0.60
    assert any("drawdown" in r for r in RiskEngine().lockouts(st))


def test_drawdown_basis_initial_vs_high_water():
    st = RiskState(31, 33, 31, 31, initial_equity=30)
    assert RiskEngine(RiskConfig(drawdown_basis="high_water")).drawdown(st) == pytest.approx(1 - 31 / 33)
    assert RiskEngine(RiskConfig(drawdown_basis="initial")).drawdown(st) == 0.0


def test_guardian_trips_protocol_and_requires_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMOVENT_EMERGENCY_POLICY", "close")
    a = app(tmp_path)
    a.agent.validated.add("t")
    a.agent.execute(Signal("t", "BTC/USDT", 1, 100, 90, 130, T), 100)
    g = RiskGuardian(a)
    a.broker.cash -= 300  # simulate a 3 % loss
    r = g.check({"BTC/USDT": 100})
    assert r["acted"] and a.broker.state.kill_switch and a.broker.state.positions == []
    assert r["steps"]["policy"] == "close" and r["steps"]["closed_positions"]
    assert a.store.risk_events()[0]["kind"] == "guardian_lock"
    assert any(x["action"] == "guardian_lock" for x in a.store.audit_log())
    with pytest.raises(OrderRejected, match="kill switch"):
        a.agent.execute(Signal("t", "ETH/USDT", 1, 100, 98, 106, T + pd.Timedelta(hours=1)), 100)
    with pytest.raises(PermissionError, match="phrase"):
        g.resume("admin", "yes")
    with pytest.raises(PermissionError, match="still breached"):
        g.resume("admin", RESUME_PHRASE)
    out = g.resume("admin", RESUME_PHRASE, reset_baseline=True)
    assert out["reset_baseline"] and not a.broker.state.kill_switch and not g.status()["locked"]
    assert app(tmp_path).store.kv_get("guardian_lock") is None


def test_guardian_protect_policy_keeps_positions_with_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMOVENT_EMERGENCY_POLICY", "protect")
    a = app(tmp_path)
    a.agent.validated.add("t")
    a.agent.execute(Signal("t", "BTC/USDT", 1, 100, 90, 130, T), 100)
    a.broker.cash -= 300
    r = RiskGuardian(a).check({"BTC/USDT": 100})
    assert r["acted"] and len(a.broker.state.positions) == 1 and r["steps"]["closed_positions"] == []


# ------------------------------------------------------------------ exchange filters, never enlarge
def test_filters_reject_instead_of_enlarging(tmp_path):
    a = App(Settings(mode=Mode.PAPER), source="synthetic", db=":memory:", keys={}, no_auth=True, redis_url="")
    a.broker = PaperBroker(a.store, 30.0, persist=False)
    a.agent.broker = a.broker
    a.agent.validated.add("t")
    binance_btc = Rules(0.00001, 0.01, 0.00001, 5.0)
    with pytest.raises(OrderRejected, match="not enlarged"):  # 2 % stop: $0.075 risk -> $3.75 notional < $5
        a.agent.execute(Signal("t", "BTC/USDT", 1, 76_000, 74_480, 80_560, T), 76_000, rules=binance_btc)
    r = a.agent.execute(Signal("t", "BTC/USDT", 1, 76_000, 75_240, 77_520, T + pd.Timedelta(hours=1)), 76_000, rules=binance_btc)
    assert r["qty"] * r["price"] >= 5 and r["decision"]["risk_amount"] <= 0.075 + 1e-9  # 1 % stop: $7.50 fits


# ------------------------------------------------------------------ opportunities
def _cand(net_min=1.5, regime="sideways", tradeable=True, stop=98.0, target=106.0):
    df = synthetic.generate(300, seed=2)
    df.iloc[-1, df.columns.get_loc("close")] = 100.0
    sig = pd.Series({"side": 1, "stop": stop, "target": target, "reason": "x"})
    reg = pd.Series({"regime": regime, "tradeable": tradeable})
    return opportunity.build("t", "BTC/USDT", "1h", df, sig, reg, {"score": 55, "direction": 1, "grade": "WATCHLIST", "unavailable": []},
                             Costs(), RiskEngine(RiskConfig(min_reward_risk=net_min)), RiskState(10_000, 10_000, 10_000, 10_000))


def test_opportunity_costs_expiry_and_waiting():
    c = _cand()
    assert c.actionable and c.expected_cost_bps == 2 * 10 + 2 + 2 * 3
    assert c.net_reward_risk < c.reward_risk and c.expires_at > c.bar_time and c.qty > 0
    assert not _cand(tradeable=False, regime="high_volatility").actionable
    thin = _cand(stop=99.5, target=100.8)  # 1.6R gross, costs push it under 1.5R net
    assert not thin.actionable and "after" in thin.reason


# ------------------------------------------------------------------ autopilot
class Stub:
    def __init__(self, a, fail=False, stale=False):
        from promovent.service import MarketService
        self.ms, self.fail, self.stale = MarketService(source="synthetic"), fail, stale
        self.exchange = "synthetic"

    def ohlcv(self, s, tf, limit=600):
        from promovent.service import DataUnavailable
        if self.fail:
            raise DataUnavailable("binance: ConnectError")
        df, meta = self.ms.ohlcv(s, tf, limit)
        meta.timestamp_ms = int(time.time() * 1000) - (600_000 if self.stale else 1000)
        return df, meta


def test_autopilot_waits_without_approved_strategy(tmp_path):
    a = app(tmp_path)
    a.market = Stub(a)
    r = Autopilot(a).step()
    assert r.decision.startswith("wait: no strategy") and a.broker.state.positions == []
    assert a.store.kv_get("autopilot_last_step")["decision"] == r.decision


@pytest.mark.parametrize("kw,gate", [({"fail": True}, "exchange_connectivity"), ({"stale": True}, "market_data_fresh")])
def test_autopilot_blocks_entries_on_bad_data(tmp_path, kw, gate):
    a = app(tmp_path)
    a.store.add(StrategyResearch(strategy="trend_following", exchange="binance", symbol="BTC/USDT", timeframe="1h", params={},
                                 data_start=T, data_end=T, bars=3000, source="live", metrics={}, walk_forward={}, monte_carlo={},
                                 passed=True, failures=[]))
    a.market = Stub(a, **kw)
    r = Autopilot(a).step()
    assert not r.entries_allowed and any(g.name == gate and not g.ok for g in r.gates) and r.decision.startswith("wait")


def test_autopilot_only_trades_live_validated_combos(tmp_path):
    a = app(tmp_path)
    base = dict(exchange="binance", timeframe="1h", params={}, data_start=T, data_end=T, bars=3000, metrics={}, walk_forward={},
                monte_carlo={}, failures=[])
    a.store.add(StrategyResearch(strategy="trend_following", symbol="BTC/USDT", source="synthetic", passed=True, **base))
    a.store.add(StrategyResearch(strategy="market_structure", symbol="ETH/USDT", source="live", passed=False, **base))
    assert Autopilot(a).approved() == []
    a.store.add(StrategyResearch(strategy="market_structure", symbol="ETH/USDT", source="live", passed=True, **base))
    assert [x["symbol"] for x in Autopilot(a).approved()] == ["ETH/USDT"]


def test_autopilot_cursor_prevents_reprocessing(tmp_path):
    a = app(tmp_path)
    a.market = Stub(a)
    a.store.add(StrategyResearch(strategy="market_structure", exchange="binance", symbol="BTC/USDT", timeframe="1h", params={}, data_start=T,
                                 data_end=T, bars=3000, source="live", metrics={}, walk_forward={}, monte_carlo={}, passed=True, failures=[]))
    p = Autopilot(a)
    p.step()
    cur = a.store.kv_get("cursor:market_structure:BTC/USDT:1h")
    assert cur and Autopilot(a)._process({"strategy": "market_structure", "symbol": "BTC/USDT", "timeframe": "1h"}, {}) is None


# ------------------------------------------------------------------ reviews and reports
def test_review_separates_luck_from_correct_prediction():
    t = {"side": 1, "entry": 100, "exit": 101, "stop": 98, "target": 106, "reason": "guardian_close", "pnl": 0.5}
    ev = review.evaluate(t, {"signal_price": 99.9, "regime": "sideways"}, "strong_bearish_trend", 3)
    assert ev["profitable"] and ev["lucky"] and ev["hypothesis"] == "undecided" and ev["regime_changed"]
    hit = review.evaluate({**t, "exit": 106, "reason": "target", "pnl": -0.1}, {}, None, 3)
    assert hit["hypothesis"] == "correct" and not hit["profitable"] and any("costs" in n for n in hit["notes"])


def test_reports_keep_paper_and_live_separate(tmp_path):
    from promovent.reports import generate
    a = app(tmp_path)
    a.agent.validated.add("t")
    a.agent.execute(Signal("t", "BTC/USDT", 1, 100, 98, 106, T), 100)
    a.broker.on_price("BTC/USDT", 107)
    c = generate(a, "daily", end=pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1))
    assert c["paper"]["closed_trades"] == 1 and c["live"]["closed_trades"] == 0
    assert c["paper"]["label"].startswith("PAPER") and c["live"]["label"].startswith("LIVE")
    assert c["paper"]["realized_pnl_net"] == pytest.approx(c["paper"]["gross_pnl"] - c["paper"]["fees"])
    md = a.store.list(Report)[0]["markdown"]
    assert "PAPER (simulated" in md and "No trades and no open positions" in md


# ------------------------------------------------------------------ research and learning
def test_hypothesis_functions_report_method_and_limits():
    from promovent.research import hypotheses as H
    df = synthetic.generate(1500, seed=4)
    f = H.b_volatility_clustering(df, "BTC/USDT", "src")
    assert {"source", "methodology", "limitations", "data_window", "conclusion"} <= set(f) and f["result"]["n"] == 1499
    v = H.i_variance_ratio(df, "BTC/USDT", "src")
    assert set(v["result"]) == {"q4", "q24"}
    L = H.l_risk_of_ruin([-1, -1, 2, 1.5, -1, 2], "src", runs=200)
    assert L["result"]["0.25%"]["p95_max_dd"] > L["result"]["1.00%"]["p95_max_dd"]
    assert H.h_onchain_not_tested()["conclusion"] == "not_tested"


def test_strategy_research_rows_and_mission(tmp_path, monkeypatch):
    from promovent.research import hypotheses, mission
    a = app(tmp_path)
    monkeypatch.setattr(hypotheses, "run_all", lambda app, mission_id=None: [])
    r = mission.cycle(a, ["BTC/USDT"], ["1h"])
    rows = a.store.list(StrategyResearch, 50)
    assert rows and all(x["source"] == "synthetic" for x in rows) and r["mission"]["cycles"] == 1
    assert any(f["area"] == "D" for f in a.store.list(ResearchFinding))
    assert not mission.due(r["mission"], pd.Timestamp.now(tz="UTC"))


def test_learning_loop_promotes_only_on_live_data(tmp_path):
    from promovent.ml import learner
    a = app(tmp_path)
    out = learner.retrain(a, ["BTC/USDT", "ETH/USDT"], bars=1200, model_dir=tmp_path)
    assert {r["kind"] for r in out["results"]} == {"lightgbm", "xgboost", "random_forest", "statistical"}
    assert out["promoted"] is None and "nothing promoted" in out["note"]  # synthetic data is never promoted
    assert learner.predict(a, ["BTC/USDT"], model_dir=tmp_path) == []
    assert learner.monitor(a)["status"] == "no resolved predictions yet"


# ------------------------------------------------------------------ Binance client hardening and data
def _bn(fake):
    return BinanceTrading(Credentials(KEY, SECRET), client=httpx.Client(transport=fake.transport()))


def test_binance_resyncs_clock_on_1021():
    fake = FakeBinance()
    fake.clock_skew_ms = 60_000  # our clock is a minute behind the exchange
    cl = _bn(fake)
    assert cl.balances()["USDT"][0] == 10_000 and abs(cl.time_offset_ms - 60_000) < 2_000


def test_binance_rate_limit_and_ban_reported():
    for code, word in ((429, "rate limited"), (418, "IP banned")):
        cl = BinanceTrading(Credentials(KEY, SECRET), client=httpx.Client(transport=httpx.MockTransport(
            lambda r, c=code: httpx.Response(c, headers={"retry-after": "30"}, json={}))))
        with pytest.raises(ExchangeUnavailable, match=word):
            cl.balances()
    cl = _bn(FakeBinance())
    cl.used_weight = 5_500
    with pytest.raises(ExchangeUnavailable, match="weight"):
        cl.balances()


def test_live_fill_fees_recorded():
    from promovent.db.models import Execution
    from promovent.execution.engine import Autonomy, LiveExecutionEngine
    from promovent.db import Store
    s = Settings(mode=Mode.AUTONOMOUS_LIVE, live_trading_enabled=True)
    store = Store()
    e = LiveExecutionEngine(s, RiskEngine(s.risk), store, _bn(FakeBinance()), {"t"}, RiskState(10_000, 10_000, 10_000, 10_000),
                            Autonomy(active=True, allowed_symbols=["BTC/USDT"], allowed_strategies=["t"], max_order_notional=5000),
                            sleep=lambda _: None)
    r = e.execute(Signal("t", "BTC/USDT", 1, 100, 98, 106, T), 100, time.time())
    ex = store.list(Execution)
    assert r["fills"] and ex and ex[0]["fee"] == pytest.approx(r["filled_qty"] * 0.001)


def test_live_preflight_blocked_by_guardian_lock():
    from promovent.db import Store
    from promovent.execution.engine import LiveExecutionEngine
    s = Settings(mode=Mode.ASSISTED_LIVE, live_trading_enabled=True)
    store = Store()
    store.kv_set("guardian_lock", {"reason": "total drawdown 2.1%"})
    e = LiveExecutionEngine(s, RiskEngine(s.risk), store, _bn(FakeBinance()), {"t"}, RiskState(10_000, 10_000, 10_000, 10_000))
    assert "guardian" in e.preflight(Signal("t", "BTC/USDT", 1, 100, 98, 106, T), 100, time.time()).as_dict()["failed"][0]


def test_universe_from_tickers():
    raw = {"code": "0", "data": [
        {"instId": "BTC-USDT", "last": "1", "volCcy24h": "9e8", "bidPx": "1", "askPx": "1.0001"},
        {"instId": "PEPE-USDT", "last": "1", "volCcy24h": "5e7", "bidPx": "1", "askPx": "1.0002"},
        {"instId": "USDC-USDT", "last": "1", "volCcy24h": "9e9"}, {"instId": "TINY-USDT", "last": "1", "volCcy24h": "10"},
        {"instId": "ETH-BTC", "last": "1", "volCcy24h": "9e9"}]}
    u = universe.build(universe.parse_okx_tickers(raw))
    assert u["core"] == ["BTC/USDT"] and u["added_by_liquidity"] == ["PEPE/USDT"] and "ETH/USDT" in u["core_not_listed"]


def test_okx_liquidations_parsed_for_watched_symbols():
    import json
    from promovent.market_data.exchange_adapters import OKXWS
    t = int(time.time() * 1000)
    msg = {"arg": {"channel": "liquidation-orders", "instType": "SWAP"}, "data": [
        {"instId": "BTC-USDT-SWAP", "details": [{"side": "sell", "posSide": "long", "bkPx": "75000", "sz": "3", "ts": str(t)}]},
        {"instId": "PEPE-USDT-SWAP", "details": [{"side": "buy", "posSide": "short", "bkPx": "1", "sz": "9", "ts": str(t)}]}]}
    ev = OKXWS(["BTC/USDT"]).parse(json.dumps(msg))
    assert len(ev) == 1 and ev[0].kind == "liquidation" and ev[0].data["pos_side"] == "long"


def test_binance_history_paging():
    H, T0 = 3_600_000, 1_704_067_200_000
    calls = []

    def h(req):
        calls.append(dict(req.url.params))
        end = int(req.url.params.get("endTime", T0 + 20 * H))
        n = int(req.url.params["limit"])
        rows = [[T0 + i * H, "1", "2", "0.5", "1.5", "3"] for i in range(max(0, end // H - T0 // H - n + 1), end // H - T0 // H + 1)
                if T0 + i * H <= end]
        return httpx.Response(200, json=rows)
    from promovent.data.exchanges import Binance
    r = Binance(httpx.Client(transport=httpx.MockTransport(h))).ohlcv("BTC/USDT", "1h", limit=15, now_ms=T0 + 20 * H + 10)
    assert len(r.df) == 15 and r.df.index.is_unique and len(calls) >= 1
    assert (r.df.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()
