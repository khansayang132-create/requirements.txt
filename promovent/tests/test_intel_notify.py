import json

import httpx
import pytest

from promovent.db import Store
from promovent.db.models import Notification
from promovent.intel import ProviderUnavailable
from promovent.intel.news import RSS, CryptoPanic, Reddit, aggregate, analyze_text, fear_greed
from promovent.intel.whale import Etherscan, Watch, WhaleAlert, WhaleSummary, classify
from promovent.notify import Email, Notifier, SMTPConfig, Telegram, render

WA = {"result": "success", "count": 3, "transactions": [
    {"blockchain": "bitcoin", "symbol": "btc", "hash": "aa", "timestamp": 1000, "amount": 500, "amount_usd": 30e6,
     "transaction_type": "transfer", "from": {"owner_type": "unknown"}, "to": {"owner": "binance", "owner_type": "exchange"}},
    {"blockchain": "bitcoin", "symbol": "btc", "hash": "bb", "timestamp": 1100, "amount": 300, "amount_usd": 18e6,
     "transaction_type": "transfer", "from": {"owner": "coinbase", "owner_type": "exchange"}, "to": {"owner_type": "unknown"}},
    {"blockchain": "ethereum", "symbol": "usdt", "hash": "cc", "timestamp": 1200, "amount": 5e7, "amount_usd": 5e7,
     "transaction_type": "mint", "from": {"owner": "tether treasury", "owner_type": "unknown"}, "to": {"owner_type": "unknown"}},
]}


def client(fn):
    return httpx.Client(transport=httpx.MockTransport(fn))


def test_whale_alert_parse_classifies_flows_not_trades():
    txs = WhaleAlert(client(lambda r: httpx.Response(200, json=WA)), api_key="k").recent()
    assert [t.flow for t in txs] == ["exchange_inflow", "exchange_outflow", "mint"]
    assert txs[0].reference == "https://www.blockchain.com/explorer/transactions/btc/aa"
    assert all("not a confirmed trade" in t.note for t in txs)
    f = WhaleSummary(txs).flows()["BTC"]
    assert f["net_exchange_flow_usd"] == 12e6


def test_whale_errors_and_missing_key(monkeypatch):
    monkeypatch.delenv("WHALE_ALERT_API_KEY", raising=False)
    with pytest.raises(ProviderUnavailable, match="WHALE_ALERT_API_KEY"):
        WhaleAlert()
    with pytest.raises(ProviderUnavailable, match="invalid key"):
        WhaleAlert(client(lambda r: httpx.Response(401, json={})), api_key="k").recent()
    with pytest.raises(ProviderUnavailable, match="rate limited"):
        WhaleAlert(client(lambda r: httpx.Response(429, json={})), api_key="k").recent()


def test_clusters_and_unusual():
    txs = WhaleAlert.parse({"result": "success", "transactions": [dict(WA["transactions"][0], hash=str(i), timestamp=1000 + 60 * i)
                                                                    for i in range(4)]})
    s = WhaleSummary(txs)
    c = s.clusters(window_s=600, min_size=3)
    assert len(c) == 1 and c[0]["count"] == 4 and c[0]["hashes"] == ["0", "1", "2", "3"]
    assert s.unusual({"BTC": [1e6] * 9 + [2e6]})[0]["asset"] == "BTC"
    assert classify("exchange", "exchange", "a", "b") == "exchange_internal"


def test_etherscan_watchlist_and_direction():
    w = Watch("my-exchange-hot", "exchange", "0xabc")
    raw = {"status": "1", "result": [
        {"hash": "0x1", "timeStamp": "5", "value": str(int(800e18)), "from": "0xdef", "to": "0xabc", "isError": "0"},
        {"hash": "0x2", "timeStamp": "6", "value": str(int(1e18)), "from": "0xabc", "to": "0xdef", "isError": "0"}]}
    e = Etherscan(client(lambda r: httpx.Response(200, json=raw)), api_key="k", watch=[w])
    txs = e.recent(min_eth=500)
    assert len(txs) == 1 and txs[0].flow == "exchange_inflow" and txs[0].reference.endswith("0x1")
    with pytest.raises(ProviderUnavailable, match="WATCH_ADDRESSES"):
        Etherscan(api_key="k", watch=[]).recent()


RSS_XML = """<?xml version="1.0"?><rss><channel>
<item><title>Exchange hacked, withdrawals halted</title><link>https://ex.com/a</link><pubDate>Sat, 07 Nov 2026 06:00:00 GMT</pubDate></item>
<item><title>Bitcoin surges to record high</title><link>https://ex.com/b</link><pubDate>Sat, 07 Nov 2026 05:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_and_sentiment():
    items = RSS(client(lambda r: httpx.Response(200, text=RSS_XML))).fetch("coindesk")
    assert items[0].sentiment["label"] == "bearish" and "exchange_incident" in items[0].sentiment["categories"]
    assert items[1].sentiment["label"] == "bullish" and items[1].sentiment["assets"] == ["BTC"]
    assert items[0].published == "2026-11-07T06:00:00+00:00" and items[0].url == "https://ex.com/a"
    agg = aggregate(items)
    assert agg["BTC"]["bullish"] == 1 and agg["MARKET"]["bearish"] == 1
    with pytest.raises(ProviderUnavailable):
        RSS(client(lambda r: httpx.Response(200, text="<not xml"))).fetch("coindesk")
    assert analyze_text("Markets quiet today")["label"] == "neutral"


def test_cryptopanic_votes_and_bad_key():
    raw = {"results": [{"title": "ETH upgrade goes live", "published_at": "2026-11-07T00:00:00Z", "url": "u",
                        "source": {"title": "The Block"}, "votes": {"negative": 9, "positive": 1}}]}
    it = CryptoPanic(client(lambda r: httpx.Response(200, json=raw)), key="k").fetch()[0]
    assert it.sentiment["label"] == "bearish" and it.sentiment["votes_used"] and it.source == "The Block"
    with pytest.raises(ProviderUnavailable, match="invalid API key"):
        CryptoPanic(client(lambda r: httpx.Response(401, json={})), key="k").fetch()


def test_reddit_oauth_flow(monkeypatch):
    for k, v in {"REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "s", "REDDIT_USER_AGENT": "promovent-test"}.items():
        monkeypatch.setenv(k, v)

    def h(req):
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(200, json={"access_token": "tok"})
        assert req.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"data": {"children": [{"data": {"title": "Solana outage again", "permalink": "/r/x/1",
                                                                         "created_utc": 0, "score": 5, "num_comments": 2}}]}})
    it = Reddit(client(h)).fetch()[0]
    assert it.source == "reddit r/CryptoCurrency" and it.sentiment["assets"] == ["SOL"]


def test_fear_greed_parse_and_failure():
    ok = client(lambda r: httpx.Response(200, json={"data": [{"value": "22", "value_classification": "Extreme Fear", "timestamp": "1"}]}))
    assert fear_greed(ok)["value"] == 22
    with pytest.raises(ProviderUnavailable):
        fear_greed(client(lambda r: httpx.Response(200, json={})))


# ---------------------------------------------------------------- notifications
def test_telegram_send_and_errors():
    sent = []

    def h(req):
        sent.append(json.loads(req.content))
        if sent[-1]["chat_id"] == "bad":
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})
        return httpx.Response(200, json={"ok": True, "result": {}})
    tg = Telegram("123:abc", client(h))
    tg.send("42", "Order <FILLED>", "x & y")
    assert sent[0]["text"].startswith("<b>Order &lt;FILLED&gt;</b>")
    from promovent.notify import SendError
    with pytest.raises(SendError, match="chat not found"):
        tg.send("bad", "s", "b")


class SMTPCapture:
    def __init__(self):
        from aiosmtpd.controller import Controller
        self.messages = []
        outer = self

        class H:
            async def handle_DATA(self, server, session, envelope):
                outer.messages.append(envelope)
                return "250 OK"
        import socket
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.ctl = Controller(H(), hostname="127.0.0.1", port=self.port)

    def __enter__(self):
        self.ctl.start()
        return self

    def __exit__(self, *a):
        self.ctl.stop()


def test_email_delivered_to_real_smtp_server_and_tracked():
    with SMTPCapture() as smtp:
        cfg = SMTPConfig("127.0.0.1", smtp.port, None, None, "bot@promovent.local", "none")
        store = Store()
        n = Notifier(store, Telegram(""), Email(cfg), sleep=lambda _: None)
        users = [{"id": None, "username": "a", "email": "a@example.com", "telegram_chat_id": "1",
                  "alert_prefs": {"execution": ["email", "telegram"]}}]
        res = n.notify("execution", {"status": "FILLED", "symbol": "BTC/USDT", "qty": 0.1, "exchange": "binance"}, users)
    assert [r["status"] for r in res] == ["sent", "skipped"]
    assert res[1]["error"] == "missing TELEGRAM_BOT_TOKEN"
    assert len(smtp.messages) == 1 and smtp.messages[0].rcpt_tos == ["a@example.com"]
    assert b"Order FILLED: BTC/USDT 0.1" in smtp.messages[0].content
    rows = store.list(Notification)
    assert {r["status"] for r in rows} == {"sent", "skipped"}


def test_email_failure_retried_and_recorded():
    cfg = SMTPConfig("127.0.0.1", 9, None, None, "bot@x", "none")
    store = Store()
    res = Notifier(store, Telegram(""), Email(cfg), sleep=lambda _: None).notify(
        "risk_warning", {"kind": "daily_loss", "detail": "2%"}, [{"email": "a@x", "alert_prefs": {"risk_warning": ["email"]}}])
    assert res[0]["status"] == "failed" and "smtp" in res[0]["error"] and store.notifications()[0]["attempts"] == 3


def test_render_missing_fields_dont_crash():
    s, b = render("signal", {"symbol": "ETH/USDT"})
    assert s.startswith("Signal: ETH/USDT -") and "Entry -" in b
