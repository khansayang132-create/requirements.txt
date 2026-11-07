"""Integration tests against real PostgreSQL and Redis servers.
Run with PROMOVENT_TEST_DATABASE_URL=postgresql+psycopg://... and PROMOVENT_TEST_REDIS_URL=redis://...
(CI starts both as service containers). Skipped otherwise, and the report says so."""
import os
import threading

import pytest
from sqlalchemy import inspect, text

from promovent.cache import Coord
from promovent.db import DatabaseUnavailable, Store, downgrade, upgrade

PG = os.getenv("PROMOVENT_TEST_DATABASE_URL")
RD = os.getenv("PROMOVENT_TEST_REDIS_URL")
need_pg = pytest.mark.skipif(not PG, reason="PROMOVENT_TEST_DATABASE_URL not set")
need_rd = pytest.mark.skipif(not RD, reason="PROMOVENT_TEST_REDIS_URL not set")
TABLES = {"users", "exchange_accounts", "market_candles", "signals", "orders", "positions", "executions", "strategies",
          "backtest_results", "portfolio_snapshots", "risk_events", "notifications", "audit_log", "alerts", "ml_models"}


@need_pg
def test_postgres_migrate_down_up_and_tables():
    downgrade(PG, "base")
    upgrade(PG)
    s = Store(PG)
    assert TABLES <= set(inspect(s.engine).get_table_names())
    assert s.health() == {"ok": True, "dialect": "postgresql"}


@need_pg
def test_postgres_transaction_integrity_and_pool():
    s = Store(PG)
    with s.engine.begin() as c:
        c.execute(text("TRUNCATE orders, positions, executions, audit_log RESTART IDENTITY CASCADE"))
    s.save_order(client_order_id="pvA", venue="binance", symbol="BTC/USDT", side=1, order_type="market", qty=1, status="NEW")
    with pytest.raises(DatabaseUnavailable):
        with s.session() as sess:  # one failing statement rolls back the whole unit of work
            from promovent.db.models import Order
            sess.add(Order(client_order_id="pvB", venue="x", symbol="BTC/USDT", side=1, order_type="m", qty=1, status="NEW"))
            sess.add(Order(client_order_id="pvA", venue="x", symbol="BTC/USDT", side=1, order_type="m", qty=1, status="NEW"))
            sess.flush()
    assert not s.order_exists("pvB")
    errs = []

    def writer(i):
        try:
            for j in range(20):
                s.audit(f"t{i}", "load", {"j": j})
        except Exception as e:  # pragma: no cover
            errs.append(e)
    ts = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(s.audit_log(1000)) == 160


@need_rd
def test_redis_rate_limit_locks_cache_heartbeat():
    a, b = Coord(RD), Coord(RD)
    a.r.flushdb()
    assert a.health()["mode"] == "redis"
    allowed = [a.allow("ip1", rate=0.001, burst=3) if i % 2 else b.allow("ip1", rate=0.001, burst=3) for i in range(6)]
    assert allowed.count(True) == 3  # shared across two clients (= two API replicas)
    t = a.acquire_lock("scan", 5)
    assert t and b.acquire_lock("scan", 5) is None
    a.release_lock("scan", t)
    assert b.acquire_lock("scan", 5)
    a.set("x", {"v": 1}, 5)
    assert b.get("x") == {"v": 1}
    assert a.heartbeat("w1", {"jobs": {}}) and "w1" in b.heartbeats()
