"""WebSocket tests against a real local websockets server speaking each exchange's message format.
The server is local: this proves reconnect/heartbeat/validation logic, not connectivity to exchanges."""
import asyncio
import json
import time

import pytest
import websockets

from promovent.market_data.candle_processor import CandleProcessor
from promovent.market_data.data_validator import DataValidator
from promovent.market_data.events import MarketEvent
from promovent.market_data.exchange_adapters import BinanceWS, BybitWS, OKXWS
from promovent.market_data.market_stream import MarketStream
from promovent.market_data.orderbook import OrderBook, SequenceGap


def now_ms():
    return int(time.time() * 1000)


def bn_trade(tid, price, ts=None):
    return json.dumps({"stream": "btcusdt@trade", "data": {"e": "trade", "E": ts or now_ms(), "s": "BTCUSDT", "t": tid,
                                                           "p": str(price), "q": "0.5", "T": ts or now_ms(), "m": False}})


def run(coro, timeout=10):
    return asyncio.run(asyncio.wait_for(coro, timeout))


def test_reconnects_after_server_drops_and_dedupes():
    connections = []

    async def handler(ws):
        connections.append(ws)
        # first connection: two trades (one duplicated) then the server drops the socket
        if len(connections) == 1:
            for m in (bn_trade(1, 100), bn_trade(1, 100), bn_trade(2, 101)):
                await ws.send(m)
            await ws.close()
        else:
            await ws.send(bn_trade(3, 102))
            await ws.wait_closed()

    async def main():
        async with websockets.serve(handler, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            ms = MarketStream("binance", ["BTC/USDT"], url=f"ws://127.0.0.1:{port}/stream")
            ms.conns[0].backoff_max = 0.2
            task = asyncio.create_task(ms.run())
            for _ in range(100):
                await asyncio.sleep(0.05)
                if ms.last.get("BTC/USDT", {}).get("price") == 102:
                    break
            ms.stop()
            await asyncio.wait_for(task, 3)
            return ms
    ms = run(main())
    snap = ms.snapshot()
    s = snap["symbols"]["BTC/USDT"]
    assert s["price"] == 102 and s["source"] == "live" and s["exchange"] == "binance" and s["timestamp_ms"]
    assert snap["connections"][0]["reconnects"] >= 1
    assert snap["validator"]["duplicates"] == 1 and snap["validator"]["accepted"] == 3


def test_stale_feed_detected_and_reconnected():
    async def handler(ws):
        await ws.send(bn_trade(int(time.time() * 1e6), 100))
        await ws.wait_closed()  # then silence until the client gives up on us

    async def main():
        async with websockets.serve(handler, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            ms = MarketStream("binance", ["BTC/USDT"], url=f"ws://127.0.0.1:{port}/", stale_after=0.3)
            ms.conns[0].backoff_max = 0.1
            task = asyncio.create_task(ms.run())
            await asyncio.sleep(1.5)
            ms.stop()
            await asyncio.wait_for(task, 3)
            return ms.conns[0].status
    st = run(main())
    assert st.stale_events >= 1 and st.reconnects >= 1  # last_error clears on each successful reconnect


def test_unreachable_server_backs_off_without_crashing():
    async def main():
        ms = MarketStream("binance", ["BTC/USDT"], url="ws://127.0.0.1:9/")
        ms.conns[0].backoff_max = 0.1
        task = asyncio.create_task(ms.run())
        await asyncio.sleep(0.8)
        ms.stop()
        await asyncio.wait_for(task, 3)
        return ms
    ms = run(main())
    c = ms.snapshot()["connections"][0]
    assert c["reconnects"] >= 2 and c["last_error"]
    assert ms.snapshot()["symbols"]["BTC/USDT"]["price"] is None  # nothing invented


def test_bybit_app_ping_and_subscription_sent():
    got = []

    async def handler(ws):
        async for m in ws:
            got.append(json.loads(m))
            if len(got) >= 2:
                break

    async def main():
        async with websockets.serve(handler, "127.0.0.1", 0) as srv:
            port = srv.sockets[0].getsockname()[1]
            ms = MarketStream("bybit", ["BTC/USDT"], url=f"ws://127.0.0.1:{port}/")
            ms.conns[0].app_ping_interval = 0.2
            task = asyncio.create_task(ms.run())
            await asyncio.sleep(1.0)
            ms.stop()
            await asyncio.wait_for(task, 3)
    run(main())
    assert got[0]["op"] == "subscribe" and "publicTrade.BTCUSDT" in got[0]["args"]
    assert {"op": "ping"} in got


def test_validator_rejects_future_old_bad_and_duplicates():
    v = DataValidator()
    t = now_ms()
    ok = MarketEvent("trade", "x", "BTC/USDT", t, {"price": 1.0}, "a")
    assert v.check(ok)[0] and not v.check(ok)[0]
    assert "future" in v.check(MarketEvent("trade", "x", "BTC/USDT", t + 60_000, {"price": 1.0}, "b"))[1]
    assert "old" in v.check(MarketEvent("trade", "x", "BTC/USDT", t - 600_000, {"price": 1.0}, "c"))[1]
    assert not v.check(MarketEvent("trade", "x", "BTC/USDT", t, {"price": -1.0}, "d"))[0]
    bad = {"open": 10, "high": 9, "low": 8, "close": 10, "volume": 1, "open_time": 0, "closed": True}
    assert not v.check(MarketEvent("candle", "x", "BTC/USDT", t, bad, "e"))[0]


def test_binance_book_sequencing():
    b = OrderBook("binance", "BTC/USDT")
    with pytest.raises(SequenceGap):
        b.delta([], [], 1, 2)
    b.snapshot([(100, 1)], [(101, 1)], seq=10)
    assert b.delta([(100, 2)], [], 5, 9) is False  # already in snapshot
    assert b.delta([(99, 1)], [(101, 0), (102, 3)], 8, 12)  # straddles 11
    assert b.best() == (100, 102) and b.bids[100] == 1
    assert b.delta([], [], 13, 14)
    with pytest.raises(SequenceGap):
        b.delta([], [], 16, 17)  # 15 missing
    assert b.needs_resync


def test_okx_prev_seq_and_bybit_snapshot_reset():
    o = OrderBook("okx", "BTC/USDT")
    o.snapshot([(1, 1)], [(2, 1)], seq=5)
    o.delta([(1, 3)], [], -1, 6, prev=5)
    with pytest.raises(SequenceGap):
        o.delta([], [], -1, 8, prev=7)
    y = OrderBook("bybit", "BTC/USDT")
    y.snapshot([(1, 1)], [(2, 1)], seq=100)
    assert y.delta([(1, 0)], [], 101, 101) and 1 not in y.bids
    assert y.delta([], [], 50, 50) is False


def test_crossed_book_forces_resync():
    b = OrderBook("bybit", "X/USDT")
    b.snapshot([(100, 1)], [(101, 1)], 1)
    with pytest.raises(SequenceGap, match="crossed"):
        b.delta([(102, 1)], [], 2, 2)


def test_parsers_all_exchanges():
    t = now_ms()
    k = BinanceWS(["BTC/USDT"]).parse(json.dumps({"data": {"e": "kline", "E": t, "s": "BTCUSDT", "k": {
        "t": 0, "T": 59999, "i": "1m", "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": True}}}))[0]
    assert k.kind == "candle" and k.data["closed"] and k.symbol == "BTC/USDT"
    f = BinanceWS(["BTC/USDT"]).parse(json.dumps({"data": {"e": "markPriceUpdate", "E": t, "s": "BTCUSDT", "p": "100", "r": "0.0001", "T": t}}))[0]
    assert f.kind == "funding" and f.data["rate"] == 0.0001
    y = BybitWS(["BTC/USDT"]).parse(json.dumps({"topic": "tickers.BTCUSDT", "ts": t, "data": {
        "symbol": "BTCUSDT", "fundingRate": "0.0002", "openInterest": "1234", "nextFundingTime": "0"}}))
    assert {e.kind for e in y} == {"funding", "open_interest"}
    ob = BybitWS(["BTC/USDT"]).parse(json.dumps({"topic": "orderbook.50.BTCUSDT", "type": "snapshot", "ts": t,
                                                 "data": {"s": "BTCUSDT", "b": [["1", "2"]], "a": [["3", "4"]], "u": 7, "seq": 1}}))[0]
    assert ob.kind == "book_snapshot" and ob.data["bids"] == [(1.0, 2.0)]
    x = OKXWS(["BTC/USDT"])
    assert x.parse("pong") == []
    c = x.parse(json.dumps({"arg": {"channel": "candle1m", "instId": "BTC-USDT"}, "data": [[str(t), "1", "2", "0.5", "1.5", "9", "0", "0", "0"]]}))[0]
    assert c.kind == "candle" and c.data["closed"] is False
    oi = x.parse(json.dumps({"arg": {"channel": "open-interest", "instId": "BTC-USDT-SWAP"}, "data": [{"oi": "55", "ts": str(t)}]}))[0]
    assert oi.symbol == "BTC/USDT" and oi.data["oi"] == 55
    with pytest.raises(ValueError):
        x.parse(json.dumps({"event": "error", "code": "60018", "msg": "bad channel"}))


def test_candle_processor_only_keeps_closed():
    cp = CandleProcessor("1m")
    base = {"high": 2, "low": 1, "open": 1, "close": 2, "volume": 1}
    ev = lambda ot, closed: MarketEvent("candle", "okx", "BTC/USDT", now_ms(), {**base, "open_time": ot, "closed": closed})  # noqa: E731
    assert cp.on_kline(ev(0, False)) is None and cp.frame("okx", "BTC/USDT").empty
    assert cp.on_kline(ev(60_000, False))["open_time"] == 0  # next candle started => previous closed
    cp.on_kline(ev(60_000, True))
    assert len(cp.frame("okx", "BTC/USDT")) == 2
    tr = CandleProcessor("1m")
    for ts, p in ((1_000, 10), (30_000, 12), (61_000, 11)):
        out = tr.on_trade(MarketEvent("trade", "x", "A/USDT", ts, {"price": p, "qty": 1}))
    assert out["high"] == 12 and out["close"] == 12 and out["volume"] == 2
