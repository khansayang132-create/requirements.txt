import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from promovent.api import App, create_app
from promovent.config import Mode, Settings
from promovent.db import Store

V, TR, AD = "v" * 24, "t" * 24, "a" * 24
H = lambda k: {"X-API-Key": k}  # noqa: E731


def mk(**kw):
    a = App(kw.pop("settings", Settings(mode=Mode.PAPER)), source="synthetic", db=":memory:",
            keys={V: "viewer", TR: "trader", AD: "admin"}, no_auth=False, redis_url=kw.pop("redis_url", ""), **kw)
    return TestClient(create_app(a)), a


def test_production_refuses_synthetic_and_no_auth(monkeypatch):
    monkeypatch.setenv("PROMOVENT_ENV", "production")
    with pytest.raises(RuntimeError, match="no generated data"):
        App(source="synthetic", keys={V: "viewer"})
    with pytest.raises(RuntimeError, match="API_KEYS"):
        App(source="live", keys={})


def test_health_reports_components():
    c, _ = mk()
    h = c.get("/api/health").json()
    assert h["database"]["ok"] and h["redis"]["mode"] == "memory"
    assert h["notifications"]["telegram"].startswith("missing")


def test_live_status_names_missing_credentials(monkeypatch):
    for v in ("PROMOVENT_BINANCE_API_KEY", "PROMOVENT_BINANCE_API_SECRET"):
        monkeypatch.delenv(v, raising=False)
    c, _ = mk(settings=Settings(mode=Mode.ASSISTED_LIVE, live_trading_enabled=True))
    s = c.get("/api/live/status", headers=H(V)).json()
    assert s["ready"] is False and "PROMOVENT_BINANCE_API_KEY" in s["problem"]


def test_autonomy_requires_admin_and_phrase():
    c, app = mk()
    assert c.post("/api/live/autonomy", json={"active": True}, headers=H(TR)).status_code == 403
    assert c.post("/api/live/autonomy", json={"active": True}, headers=H(AD)).status_code == 400
    r = c.post("/api/live/autonomy", json={"active": True, "allowed_symbols": ["BTC/USDT"], "allowed_strategies": ["x"],
                                           "confirm_phrase": "I ACCEPT AUTONOMOUS LIVE TRADING"}, headers=H(AD))
    assert r.json()["active"] and app.autonomy.active


def test_alert_settings_roundtrip_and_validation():
    c, _ = mk()
    assert c.put("/api/settings/alerts", json={"email": "not-an-email"}, headers=H(V)).status_code == 422
    assert c.put("/api/settings/alerts", json={"alert_prefs": {"bogus": ["email"]}}, headers=H(V)).status_code == 422
    r = c.put("/api/settings/alerts", json={"email": "me@example.com", "telegram_chat_id": "12345",
                                            "alert_prefs": {"execution": ["email"]}}, headers=H(V)).json()
    assert r["email"] == "me@example.com" and r["alert_prefs"] == {"execution": ["email"]}
    t = c.post("/api/settings/alerts/test", headers=H(V)).json()
    assert {x["status"] for x in t} == {"skipped"}  # no SMTP/Telegram configured in tests: reported, not faked


def test_stream_whales_news_report_unavailable(monkeypatch):
    for v in ("WHALE_ALERT_API_KEY", "ETHERSCAN_API_KEY", "CRYPTOPANIC_API_KEY", "REDDIT_CLIENT_ID"):
        monkeypatch.delenv(v, raising=False)
    c, _ = mk()
    assert c.get("/api/stream", headers=H(V)).json()["available"] is False
    w = c.get("/api/whales", headers=H(V)).json()
    assert w["transactions"] == [] and "WHALE_ALERT_API_KEY" in w["errors"]["whale-alert"]


def test_validation_persists_across_restart(tmp_path):
    url = f"sqlite:///{tmp_path}/v.db"
    a = App(Settings(mode=Mode.PAPER), source="synthetic", db=url, keys={AD: "admin"}, no_auth=False, redis_url="")
    c = TestClient(create_app(a))
    v = c.post("/api/validate", json={"strategy": "market_structure", "bars": 3000}, headers=H(AD)).json()
    b = App(Settings(mode=Mode.PAPER), source="synthetic", db=url, keys={AD: "admin"}, no_auth=False, redis_url="")
    assert ("market_structure" in b.agent.validated) == v["gate"]["passed"]
    from promovent.db.models import BacktestResult, Strategy
    assert b.store.list(Strategy)[0]["name"] == "market_structure"
    c.post("/api/backtest", json={"strategy": "trend_following", "bars": 500}, headers=H(AD))
    assert b.store.list(BacktestResult)[0]["strategy"] == "trend_following"


def test_database_outage_returns_503(tmp_path):
    c, app = mk()
    app.store.engine.dispose()
    from sqlalchemy import create_engine
    app.store.engine = create_engine("postgresql+psycopg://x:y@127.0.0.1:1/none")
    from sqlalchemy.orm import sessionmaker
    app.store.Session = sessionmaker(app.store.engine)
    assert c.get("/api/health").status_code == 503
    r = c.get("/api/alerts", headers=H(V))
    assert r.status_code == 503 and r.json()["error"] == "database unavailable"


def test_redis_outage_degrades_rate_limit_and_locks():
    from promovent.cache import Coord
    co = Coord("redis://127.0.0.1:1/0")
    assert co.health()["mode"] == "degraded-memory"
    assert co.allow("x", rate=1, burst=2) and co.allow("x", rate=1, burst=2) and not co.allow("x", rate=0.001, burst=2)
    assert co.acquire_lock("job") is None  # fails closed
    co.set("k", {"a": 1}, 5)
    assert co.get("k") == {"a": 1}


def test_worker_starts_and_stops_on_sigterm(tmp_path):
    env = {**os.environ, "PROMOVENT_SOURCE": "synthetic", "PROMOVENT_DEV_NO_AUTH": "yes", "PROMOVENT_NO_AUTOAPP": "1",
           "PROMOVENT_DATABASE_URL": f"sqlite:///{tmp_path}/w.db", "PROMOVENT_REDIS_URL": "", "PROMOVENT_SCAN_MINUTES": "0.02"}
    root = os.path.dirname(os.path.dirname(__file__))
    p = subprocess.Popen([sys.executable, "-m", "promovent.worker"], cwd=root, env=env, stderr=subprocess.PIPE, text=True)
    time.sleep(6)
    p.terminate()
    out = p.communicate(timeout=10)[1]
    assert p.returncode == 0, out[-2000:]
    assert "started" in out and "stopped" in out
    assert Store(f"sqlite:///{tmp_path}/w.db").alerts(), "scan job should have stored alerts from synthetic data"
