import pytest
from fastapi.testclient import TestClient

from promovent.api import App, _parse_keys, create_app
from promovent.config import Mode, Settings

V, TR, AD = "v" * 24, "t" * 24, "a" * 24


@pytest.fixture()
def client():
    app = App(Settings(mode=Mode.PAPER), source="synthetic", db=":memory:",
              keys={V: "viewer", TR: "trader", AD: "admin"}, no_auth=False)
    return TestClient(create_app(app)), app


def h(k):
    return {"X-API-Key": k}


def test_auth_required_and_roles(client):
    c, _ = client
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers=h("wrong" * 6)).status_code == 401
    assert c.get("/api/status", headers=h(V)).json()["source"] == "synthetic"
    assert c.post("/api/paper/order", json={"strategy": "market_structure", "symbol": "BTC/USDT"}, headers=h(V)).status_code == 403
    assert c.get("/api/audit", headers=h(TR)).status_code == 403


def test_market_endpoints_carry_meta(client):
    c, _ = client
    o = c.get("/api/ohlcv?symbol=ETH/USDT&timeframe=4h&limit=100", headers=h(V)).json()
    assert len(o["candles"]) == 100 and o["meta"]["source"] == "synthetic" and o["meta"]["symbol"] == "ETH/USDT"
    a = c.get("/api/analysis?symbol=BTC/USDT", headers=h(V)).json()
    assert {"supporting", "conflicting", "invalidation", "meta", "regime"} <= set(a)
    s = c.get("/api/scan", headers=h(V)).json()
    assert len(s["results"]) == 10
    n1 = len(c.get("/api/alerts?limit=500", headers=h(V)).json())
    c.get("/api/scan", headers=h(V))
    assert len(c.get("/api/alerts?limit=500", headers=h(V)).json()) == n1  # no duplicate alerts on refresh
    a2 = c.get("/api/ohlcv?symbol=BTC/USDT&timeframe=1h&limit=100", headers=h(V)).json()
    assert a2["meta"]["timestamp_ms"] == a["meta"]["timestamp_ms"]  # chart and copilot see the same bars


def test_input_validation(client):
    c, _ = client
    assert c.get("/api/ohlcv?symbol=../etc&timeframe=1h", headers=h(V)).status_code == 422
    assert c.get("/api/ohlcv?symbol=BTC/USDT&timeframe=7m", headers=h(V)).status_code == 422
    assert c.post("/api/backtest", json={"strategy": "nope"}, headers=h(V)).status_code == 404
    assert c.post("/api/backtest", json={"strategy": "trend_following", "bars": 10}, headers=h(V)).status_code == 422


def test_backtest_and_validate_flow(client):
    c, app = client
    b = c.post("/api/backtest", json={"strategy": "market_structure", "bars": 1500}, headers=h(V)).json()
    assert "metrics" in b and "monte_carlo" in b and b["meta"]["source"] == "synthetic"
    v = c.post("/api/validate", json={"strategy": "market_structure", "bars": 3000}, headers=h(AD)).json()
    assert "gate" in v and isinstance(v["gate"]["passed"], bool)
    assert (v["gate"]["passed"]) == ("market_structure" in app.agent.validated)


def test_order_requires_validation_then_kill_switch(client):
    c, app = client
    r = c.post("/api/paper/order", json={"strategy": "trend_following", "symbol": "BTC/USDT"}, headers=h(TR))
    assert r.status_code in (200, 409)
    if r.status_code == 200:
        assert r.json()["placed"] is False or "validation" in r.text
    app.agent.validated.add("trend_following")
    assert c.post("/api/kill", json={"reason": "drill"}, headers=h(TR)).json()["kill_switch"]
    assert c.get("/api/portfolio", headers=h(V)).json()["kill_switch"] is True
    assert c.post("/api/kill/release", headers=h(TR)).status_code == 403
    assert c.post("/api/kill/release", headers=h(AD)).json()["kill_switch"] is False
    assert any(x["action"] == "kill_switch" for x in c.get("/api/audit", headers=h(AD)).json())


def test_rate_limit(client):
    c, app = client
    app.limiter.burst, app.limiter.rate = 5, 0.0001
    codes = [c.get("/api/status", headers=h(V)).status_code for _ in range(8)]
    assert 429 in codes


def test_key_format_enforced():
    with pytest.raises(ValueError):
        _parse_keys("short:admin")
    with pytest.raises(ValueError):
        _parse_keys(("x" * 30) + ":root")
    assert _parse_keys(("x" * 30) + ":viewer") == {"x" * 30: "viewer"}


def test_dashboard_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "Promovent" in r.text
