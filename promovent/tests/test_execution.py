import time

import httpx
import pandas as pd
import pytest

from promovent.config import Mode, Settings
from promovent.db import Store
from promovent.execution import signing
from promovent.execution.clients import (AuthError, BinanceTrading, BybitTrading, Credentials, InsufficientBalance,
                                         MissingCredentials, OKXTrading, client_from_env)
from promovent.execution.engine import Autonomy, LiveExecutionEngine, LiveOrderRejected
from promovent.models import Signal
from promovent.risk import RiskEngine, RiskState

from .fake_exchanges import KEY, SECRET, FakeBinance, body, ok_bybit, verify_bybit, verify_okx

T = pd.Timestamp("2026-01-01", tz="UTC")
CREDS = Credentials(KEY, SECRET)


def test_binance_signature_matches_official_example():
    # Example from Binance "SIGNED endpoint security" docs
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    q = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
    assert signing.binance(secret, q) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_okx_signature_is_base64_hmac():
    s = signing.okx("secret", "2020-12-08T09:08:57.715Z", "get", "/api/v5/account/balance?ccy=BTC")
    import base64
    assert len(base64.b64decode(s)) == 32


def engine(fake: FakeBinance, mode=Mode.ASSISTED_LIVE, live=True, validated=("t",), autonomy=None, equity=10_000.0, **kw):
    s = Settings(mode=mode, live_trading_enabled=live)
    store = Store()
    cl = BinanceTrading(CREDS, testnet=True, client=httpx.Client(transport=fake.transport()))
    e = LiveExecutionEngine(s, RiskEngine(s.risk), store, cl, set(validated), RiskState(equity, equity, equity, equity),
                            autonomy=autonomy, sleep=lambda _: None, **kw)
    return e, store


def sig(side=1, stop=98.0, target=106.0, sym="BTC/USDT", t=T):
    return Signal("t", sym, side, 100.0, stop, target, t)


NOW = time.time


def test_missing_credentials_named(monkeypatch):
    for v in ("PROMOVENT_BINANCE_API_KEY", "PROMOVENT_BINANCE_API_SECRET"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(MissingCredentials, match="PROMOVENT_BINANCE_API_KEY, PROMOVENT_BINANCE_API_SECRET"):
        client_from_env("binance")
    with pytest.raises(MissingCredentials, match="PASSPHRASE"):
        OKXTrading(Credentials("k", "s"))


def test_invalid_api_key_reported():
    fake = FakeBinance()
    cl = BinanceTrading(Credentials("wrong" * 4, SECRET), client=httpx.Client(transport=fake.transport()))
    with pytest.raises(AuthError, match="-2015"):
        cl.balances()
    e, _ = engine(fake)
    e.client = cl
    pf = e.preflight(sig(), 100.0, NOW())
    assert not pf.ok and pf.checks[-1].name == "connection" and "API key" in pf.checks[-1].detail


def test_bad_secret_signature_rejected():
    fake = FakeBinance()
    cl = BinanceTrading(Credentials(KEY, "nope"), client=httpx.Client(transport=fake.transport()))
    with pytest.raises(AuthError, match="-1022"):
        cl.permissions()


def test_modes_1_to_3_cannot_send_live_orders():
    for m in (Mode.OBSERVATION, Mode.SIGNAL, Mode.PAPER):
        e, _ = engine(FakeBinance(), mode=m, live=False)
        assert e.preflight(sig(), 100, NOW()).checks[0].name == "mode"


def test_assisted_requires_confirmation_then_fills_and_protects():
    fake = FakeBinance()
    e, store = engine(fake)
    prop = e.propose(sig(), 100.0, NOW(), "alice")
    assert prop["preflight"]["ok"] and prop["qty"] > 0
    assert not [r for r in fake.requests if r.method == "POST"]  # nothing sent before confirmation
    res = e.confirm(prop["token"], 100.0, NOW(), "alice")
    assert res["status"] == "FILLED" and res["filled_qty"] == pytest.approx(prop["qty"])
    assert res["protection"]["ok"] and res["protection"]["take_profit"] == "on exchange (OCO)"
    oco = [r for r in fake.requests if r.url.path == "/api/v3/orderList/oco"][0]
    assert "belowType=STOP_LOSS_LIMIT" in str(oco.url) and "belowStopPrice=98" in str(oco.url)
    assert store.get_order(res["client_order_id"])["status"] == "FILLED"
    assert len(store.positions("binance")) == 1
    with pytest.raises(LiveOrderRejected, match="unknown or already used"):
        e.confirm(prop["token"], 100.0, NOW(), "alice")


def test_confirmation_expires():
    fake = FakeBinance()
    clock = [1000.0]
    e, _ = engine(fake, now=lambda: clock[0])
    prop = e.propose(sig(), 100.0, 1000.0, "a")
    clock[0] += 500
    with pytest.raises(LiveOrderRejected, match="expired"):
        e.confirm(prop["token"], 100.0, clock[0], "a")


def test_withdrawal_enabled_key_refused():
    e, _ = engine(FakeBinance(withdrawals=True))
    pf = e.preflight(sig(), 100.0, NOW())
    assert not pf.ok and "WITHDRAWALS ENABLED" in pf.as_dict()["failed"][0]


def test_mainnet_refuses_unknown_withdrawal_flag():
    fake = FakeBinance(sapi=False)
    e, _ = engine(fake)
    e.client.testnet = False
    assert "could not confirm withdrawals" in e.preflight(sig(), 100.0, NOW()).as_dict()["failed"][0]


def test_cannot_trade_key_refused():
    assert "cannot trade" in engine(FakeBinance(can_trade=False))[0].preflight(sig(), 100, NOW()).as_dict()["failed"][0]


def test_insufficient_balance_preflight_and_exchange():
    e, _ = engine(FakeBinance(usdt=3.0))
    assert e.preflight(sig(), 100.0, NOW()).as_dict()["failed"][0].startswith("balance")
    fake = FakeBinance(usdt=10.0)
    cl = BinanceTrading(CREDS, client=httpx.Client(transport=fake.transport()))
    with pytest.raises(InsufficientBalance):
        cl.place("BTC/USDT", 1, "market", 1.0, "pvx")


def test_stale_data_missing_stop_short_and_unvalidated():
    e, _ = engine(FakeBinance())
    assert e.preflight(sig(), 100.0, NOW() - 600).as_dict()["failed"][0].startswith("market_data")
    assert e.preflight(sig(stop=0), 100.0, NOW()).as_dict()["failed"][0].startswith("stop_loss")
    assert e.preflight(sig(stop=101), 100.0, NOW()).as_dict()["failed"][0].startswith("stop_loss")
    assert e.preflight(sig(side=-1, stop=102, target=94), 100.0, NOW()).as_dict()["failed"][0].startswith("long_only")
    e2, _ = engine(FakeBinance(), validated=())
    assert e2.preflight(sig(), 100.0, NOW()).as_dict()["failed"][0].startswith("strategy")


def test_daily_loss_limit_blocks_live():
    e, _ = engine(FakeBinance())
    e.state.equity, e.state.day_start_equity = 9_700, 10_000
    assert "daily loss" in e.preflight(sig(), 100.0, NOW()).as_dict()["failed"][0]


def test_duplicate_order_blocked_locally_and_on_exchange():
    fake = FakeBinance()
    e, store = engine(fake, mode=Mode.AUTONOMOUS_LIVE,
                      autonomy=Autonomy(active=True, allowed_symbols=["BTC/USDT"], allowed_strategies=["t"], max_order_notional=5000))
    e.execute(sig(), 100.0, NOW())
    with pytest.raises(LiveOrderRejected, match="duplicate"):
        e.execute(sig(), 100.0, NOW())
    e2, _ = engine(fake, mode=Mode.AUTONOMOUS_LIVE,
                   autonomy=Autonomy(active=True, allowed_symbols=["BTC/USDT"], allowed_strategies=["t"], max_order_notional=5000))
    assert "exchange already has order" in e2.preflight(sig(), 100.0, NOW()).as_dict()["failed"][0]


def test_autonomous_needs_activation_and_allow_lists():
    e, _ = engine(FakeBinance(), mode=Mode.AUTONOMOUS_LIVE)
    with pytest.raises(LiveOrderRejected, match="not activated"):
        e.execute(sig(), 100.0, NOW())
    e.autonomy = Autonomy(active=True, allowed_symbols=["ETH/USDT"], allowed_strategies=["t"])
    with pytest.raises(LiveOrderRejected, match="allowed_symbols"):
        e.execute(sig(), 100.0, NOW())
    with pytest.raises(LiveOrderRejected, match="assisted mode"):
        engine(FakeBinance())[0].execute(sig(), 100.0, NOW())


def test_autonomous_caps_order_notional():
    e, _ = engine(FakeBinance(), mode=Mode.AUTONOMOUS_LIVE,
                  autonomy=Autonomy(active=True, allowed_symbols=["BTC/USDT"], allowed_strategies=["t"], max_order_notional=50))
    r = e.execute(sig(), 100.0, NOW())
    assert r["filled_qty"] * 100 <= 50 + 1e-9


def test_partial_fill_protects_filled_and_cancels_rest():
    fake = FakeBinance(fill_mode="partial")
    e, store = engine(fake, mode=Mode.AUTONOMOUS_LIVE, fill_timeout_s=0,
                      autonomy=Autonomy(active=True, allowed_symbols=["BTC/USDT"], allowed_strategies=["t"], max_order_notional=5000))
    r = e.execute(sig(), 100.0, NOW())
    assert r["status"] == "CANCELED" and 0 < r["filled_qty"] < 25
    assert r["protection"]["ok"] and r["protection"]["qty"] <= r["filled_qty"]
    assert any(req.method == "DELETE" for req in fake.requests)


def test_protection_failure_flattens_and_kills():
    fake = FakeBinance(oco_fails=True)
    e, store = engine(fake, mode=Mode.AUTONOMOUS_LIVE,
                      autonomy=Autonomy(active=True, allowed_symbols=["BTC/USDT"], allowed_strategies=["t"], max_order_notional=5000))
    r = e.execute(sig(), 100.0, NOW())
    assert r["protection"]["ok"] is False and r["protection"]["action"] == "position closed at market"
    assert e.state.kill_switch
    assert store.risk_events()[0]["kind"] == "protection_failed"
    assert fake.bal["BTC"][0] == pytest.approx(r["filled_qty"] * 0.001, abs=1e-4)  # sold back (fee buffer remains)


def test_reconcile_updates_and_flags_missing():
    fake = FakeBinance(fill_mode="none")
    e, store = engine(fake, mode=Mode.AUTONOMOUS_LIVE, fill_timeout_s=10, poll_s=100,
                      autonomy=Autonomy(active=True, allowed_symbols=["BTC/USDT"], allowed_strategies=["t"], max_order_notional=5000))
    store.save_order(client_order_id="pvghost", venue="binance", symbol="BTC/USDT", side=1, order_type="market",
                     qty=1, status="SUBMITTING")
    store.save_order(client_order_id="pvlive", venue="binance", symbol="BTC/USDT", side=1, order_type="limit",
                     qty=1, status="NEW")
    fake.orders["pvlive"] = {"clientOrderId": "pvlive", "orderId": 5, "status": "FILLED", "executedQty": "1",
                             "cummulativeQuoteQty": "100"}
    rep = e.reconcile()
    assert rep["missing_on_exchange"] == ["pvghost"] and store.get_order("pvghost")["status"] == "REJECTED"
    assert rep["changed"][0]["to"] == "FILLED"


def test_exchange_disconnect_reported():
    def boom(req):
        raise httpx.ConnectError("connection refused")
    e, _ = engine(FakeBinance())
    e.client.http = httpx.Client(transport=httpx.MockTransport(boom))
    pf = e.preflight(sig(), 100.0, NOW())
    assert pf.checks[-1].name == "connection" and "ConnectError" in pf.checks[-1].detail


def test_bybit_signed_flow_and_errors():
    seen = []

    def h(req):
        seen.append(req)
        assert verify_bybit(req), "bad bybit signature"
        p = req.url.path
        if p == "/v5/user/query-api":
            return httpx.Response(200, json=ok_bybit({"readOnly": 0, "permissions": {"Spot": ["SpotTrade"], "Wallet": ["AccountTransfer"]}}))
        if p == "/v5/account/wallet-balance":
            return httpx.Response(200, json=ok_bybit({"list": [{"coin": [{"coin": "USDT", "walletBalance": "50", "locked": "5"}]}]}))
        if p == "/v5/order/create":
            b = body(req)
            assert b["category"] == "spot" and b["marketUnit"] == "baseCoin"
            if float(b["qty"]) > 1:
                return httpx.Response(200, json={"retCode": 170131, "retMsg": "Insufficient balance."})
            return httpx.Response(200, json=ok_bybit({"orderId": "1", "orderLinkId": b["orderLinkId"]}))
        return httpx.Response(200, json={"retCode": 10003, "retMsg": "API key is invalid."})
    cl = BybitTrading(CREDS, client=httpx.Client(transport=httpx.MockTransport(h)))
    p = cl.permissions()
    assert p.can_trade and p.withdrawals_enabled is False
    assert cl.balances()["USDT"] == (45.0, 5.0)
    assert cl.place("BTC/USDT", 1, "market", 0.5, "pvabc").exchange_id == "1"
    with pytest.raises(InsufficientBalance):
        cl.place("BTC/USDT", 1, "market", 2, "pvabd")
    with pytest.raises(AuthError):
        cl.get("BTC/USDT", "x")


def test_bybit_withdraw_permission_detected():
    h = lambda r: httpx.Response(200, json=ok_bybit({"readOnly": 0, "permissions": {"Spot": ["SpotTrade"], "Wallet": ["Withdraw"]}}))  # noqa: E731
    assert BybitTrading(CREDS, client=httpx.Client(transport=httpx.MockTransport(h))).permissions().withdrawals_enabled


def test_okx_signed_flow_demo_header_and_errors():
    creds = Credentials(KEY, SECRET, "pp")

    def h(req):
        p = req.url.path
        assert p.startswith("/api/v5/public/") or verify_okx(req, "pp"), "bad okx signature"
        assert req.headers["x-simulated-trading"] == "1"
        if p == "/api/v5/account/config":
            return httpx.Response(200, json={"code": "0", "data": [{"perm": "read_only,trade", "acctLv": "1"}]})
        if p == "/api/v5/trade/order":
            b = body(req)
            assert b["tdMode"] == "cash" and b["tgtCcy"] == "base_ccy"
            return httpx.Response(200, json={"code": "1", "msg": "", "data": [{"sCode": "51008", "sMsg": "Insufficient balance"}]})
        if p == "/api/v5/public/instruments":
            return httpx.Response(200, json={"code": "0", "data": [{"lotSz": "0.0001", "tickSz": "0.1", "minSz": "0.0001"}]})
        if p == "/api/v5/trade/order-algo":
            b = body(req)
            assert b["ordType"] == "oco" and b["slTriggerPx"] == "98" and b["tpTriggerPx"] == "106"
            return httpx.Response(200, json={"code": "0", "data": [{"algoId": "7", "algoClOrdId": b["algoClOrdId"], "sCode": "0"}]})
        return httpx.Response(200, json={"code": "50111", "msg": "Invalid OK-ACCESS-KEY", "data": []})
    cl = OKXTrading(creds, testnet=True, client=httpx.Client(transport=httpx.MockTransport(h)))
    p = cl.permissions()
    assert p.can_trade and p.withdrawals_enabled is False
    with pytest.raises(InsufficientBalance):
        cl.place("BTC/USDT", 1, "market", 1, "pvx")
    assert cl.protect("BTC/USDT", 0.5, 98, 106, "pvp")[0].exchange_id == "7"
    with pytest.raises(AuthError):
        cl.balances()


def test_rules_rounding():
    from promovent.execution.clients import Rules
    r = Rules(0.001, 0.01, 0.001, 5)
    assert r.qty(1.23456) == 1.234 and r.price(100.005) == 100.01


def test_credentials_repr_hides_secret():
    assert SECRET not in repr(CREDS) and KEY not in repr(CREDS)
