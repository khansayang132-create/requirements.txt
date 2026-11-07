"""Adapters against response shapes from each exchange's public API docs.
These fixtures are hand-built to the documented format, not recorded live
(the dev sandbox blocks exchange hosts). Live checks: STATUS.md."""
import httpx
import pandas as pd
import pytest

from promovent.data.exchanges import Binance, Bybit, Coinbase, ExchangeError, OKX, cross_exchange_prices, get_adapter
from promovent.models import DataValidationError, validate_ohlcv

H = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01T00:00Z
NOW = T0 + 3 * H + 10   # bars at T0, T0+H, T0+2H closed; T0+3H is forming


def k(ts, o, h, lo, c, v):
    return [ts, str(o), str(h), str(lo), str(c), str(v)]


def test_binance_klines_drop_forming_candle():
    raw = [k(T0 + i * H, 100 + i, 101 + i, 99 + i, 100.5 + i, 10) + [T0 + (i + 1) * H - 1, "0", 0, "0", "0", "0"]
           for i in range(4)]
    df = Binance.parse_klines(raw, "1h", NOW)
    assert len(df) == 3 and df.index[0] == pd.Timestamp("2024-01-01", tz="UTC")
    assert df["close"].iloc[-1] == 102.5


def test_bybit_newest_first_and_error_code():
    rows = [k(T0 + i * H, 1, 2, 0.5, 1.5, 3) + ["4.5"] for i in reversed(range(3))]
    df = Bybit.parse_klines({"retCode": 0, "result": {"list": rows}}, "1h", NOW)
    assert df.index.is_monotonic_increasing and len(df) == 3
    with pytest.raises(ExchangeError):
        Bybit.parse_klines({"retCode": 10001, "retMsg": "params error"}, "1h", NOW)


def test_okx_respects_confirm_flag():
    rows = [[str(T0 + i * H), "1", "2", "0.5", "1.5", "3", "4", "4", "1"] for i in range(3)]
    rows.append([str(T0 + 3 * H), "1", "2", "0.5", "1.5", "3", "4", "4", "0"])
    df = OKX.parse_klines({"code": "0", "data": list(reversed(rows))}, "1h", NOW + 2 * H)
    assert len(df) == 3


def test_coinbase_column_order():
    raw = [[T0 // 1000 + i * 3600, 99, 105, 100, 104, 7] for i in range(3)]  # time, low, high, open, close, vol
    df = Coinbase.parse_candles(raw, "1h", NOW)
    r = df.iloc[0]
    assert (r.open, r.high, r.low, r.close, r.volume) == (100, 105, 99, 104, 7)


def test_coinbase_unsupported_timeframe():
    with pytest.raises(ExchangeError):
        Coinbase(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))).ohlcv("BTC/USD", "4h")


def test_books_and_trades():
    b = Binance.parse_book({"bids": [["100", "1"], ["99", "2"]], "asks": [["101", "1"], ["102", "3"]]})
    assert b.bids[0] == (100.0, 1.0)
    with pytest.raises(ValueError):
        Binance.parse_book({"bids": [["101", "1"]], "asks": [["100", "1"]]})  # crossed
    tr = Bybit.parse_trades({"retCode": 0, "result": {"list": [
        {"price": "10", "size": "1", "side": "Sell", "time": "2"}, {"price": "11", "size": "2", "side": "Buy", "time": "1"}]}})
    assert [t["ts"] for t in tr] == [1, 2] and tr[1]["is_buyer_maker"]
    cb = Coinbase.parse_trades([{"price": "1", "size": "1", "side": "buy", "time": "2024-01-01T00:00:00Z"}])
    assert cb[0]["is_buyer_maker"]  # coinbase side is the maker side


def test_funding_parsers():
    f = Binance.parse_funding({"lastFundingRate": "0.0001", "nextFundingTime": 1, "markPrice": "100"}, {"openInterest": "5"})
    assert f["rate"] == 0.0001 and f["open_interest"] == 5
    o = OKX.parse_funding({"code": "0", "data": [{"fundingRate": "-0.0002", "nextFundingTime": "9"}]},
                          {"code": "0", "data": [{"oi": "12"}]})
    assert o["rate"] == -0.0002 and o["open_interest"] == 12


def test_http_failure_raises_not_fabricates():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="blocked")))
    a = Binance(client)
    with pytest.raises(ExchangeError, match="HTTP 403"):
        a.ohlcv("BTC/USDT", "1h")
    assert a.health()["ok"] is False
    res = cross_exchange_prices("BTC/USDT", [a])
    assert res["prices"] == {} and "binance" in res["errors"] and res["max_spread_bps"] is None


def test_mock_transport_end_to_end_with_meta():
    def handler(req):
        assert req.url.path == "/api/v3/klines" and req.url.params["symbol"] == "ETHUSDT"
        return httpx.Response(200, json=[k(T0 + i * H, 10, 11, 9, 10.5, 1) for i in range(3)])
    r = Binance(httpx.Client(transport=httpx.MockTransport(handler))).ohlcv("ETH/USDT", "1h", now_ms=NOW)
    assert r.meta.exchange == "binance" and r.meta.symbol == "ETH/USDT" and r.meta.source == "live"
    assert r.meta.age_seconds >= 0


def test_validation_rejects_bad_candles():
    idx = pd.date_range("2024-01-01", periods=2, freq="1h", tz="UTC")
    bad = pd.DataFrame({"open": [10, 10], "high": [9, 11], "low": [8, 9], "close": [10, 10], "volume": [1, 1]}, index=idx)
    with pytest.raises(DataValidationError):
        validate_ohlcv(bad)
    with pytest.raises(DataValidationError):
        validate_ohlcv(bad.iloc[::-1])


def test_unknown_exchange_and_symbol():
    with pytest.raises(ExchangeError):
        get_adapter("ftx")
    with pytest.raises(DataValidationError):
        Binance().market_id("BTCUSDT; DROP")
