"""News and sentiment.

Sources (each needs network access; keys where noted):
- CryptoPanic  developer API v2 (CRYPTOPANIC_API_KEY): aggregated crypto news with community votes.
- RSS: CoinDesk (https://www.coindesk.com/arc/outboundfeeds/rss/), Cointelegraph (https://cointelegraph.com/rss).
- Reddit (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT): application-only OAuth,
  /r/CryptoCurrency and /r/Bitcoin new posts.
- Fear & Greed index (alternative.me, no key).
- Official exchange announcements: Bybit and OKX public announcement APIs (ExchangeAnnouncements).
  Binance has no documented announcements API; its site is not scraped.

Sentiment is a transparent lexicon score in [-1, 1] over the headline/title (word lists below),
plus CryptoPanic's own bullish/bearish votes when present. It is a rough tag, not a forecast.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import httpx

from . import ProviderUnavailable, require_env

BULL = {"surge", "surges", "rally", "rallies", "soar", "soars", "record", "high", "approve", "approved", "approval", "bullish",
        "gain", "gains", "jump", "jumps", "adopt", "adoption", "inflow", "inflows", "breakout", "upgrade", "partnership", "launch"}
BEAR = {"crash", "crashes", "plunge", "plunges", "drop", "drops", "hack", "hacked", "exploit", "lawsuit", "sue", "sues",
        "ban", "bans", "bearish", "outflow", "outflows", "liquidation", "liquidations", "fraud", "halt", "halts", "delist",
        "delisting", "fine", "fined", "selloff", "sell-off", "outage", "fall", "falls", "decline", "warning"}
CATEGORIES = {
    "regulatory": {"sec", "cftc", "regulator", "regulation", "regulatory", "lawsuit", "court", "ban", "bill", "law", "license",
                   "mica", "fined", "fine", "sanction", "etf"},
    "exchange_incident": {"hack", "hacked", "exploit", "outage", "halt", "halts", "withdrawals", "suspend", "suspends", "breach",
                          "insolvent", "delist", "delisting", "maintenance"},
    "token_event": {"listing", "lists", "unlock", "airdrop", "upgrade", "fork", "mainnet", "burn", "halving", "launch"},
}
ASSETS = {"BTC": {"bitcoin", "btc"}, "ETH": {"ethereum", "ether", "eth"}, "SOL": {"solana", "sol"}, "XRP": {"xrp", "ripple"},
          "BNB": {"bnb"}, "ADA": {"cardano", "ada"}, "DOGE": {"dogecoin", "doge"}, "LINK": {"chainlink", "link"},
          "AVAX": {"avalanche", "avax"}, "DOT": {"polkadot", "dot"}}
WORD = re.compile(r"[a-z][a-z\-]+")


def analyze_text(text: str) -> dict:
    words = WORD.findall(text.lower())
    ws = set(words)
    b, s = sum(w in BULL for w in words), sum(w in BEAR for w in words)
    score = (b - s) / max(b + s, 1)
    label = "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"
    return {"score": round(score, 3), "label": label, "categories": sorted(c for c, kw in CATEGORIES.items() if ws & kw),
            "assets": sorted(a for a, kw in ASSETS.items() if ws & kw)}


@dataclass
class NewsItem:
    source: str
    title: str
    url: str
    published: str           # ISO 8601 from the provider
    provider: str
    sentiment: dict = field(default_factory=dict)
    votes: dict | None = None

    def as_dict(self):
        return self.__dict__.copy()


def _iso(rfc822: str) -> str:
    try:
        return parsedate_to_datetime(rfc822).isoformat()
    except (TypeError, ValueError):
        return rfc822


class RSS:
    FEEDS = {"coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/", "cointelegraph": "https://cointelegraph.com/rss"}

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": "promovent/2.5"})

    @staticmethod
    def parse(xml: str, source: str) -> list[NewsItem]:
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            raise ProviderUnavailable(f"{source}: invalid RSS: {e}") from e
        out = []
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            if not title:
                continue
            out.append(NewsItem(source, title, (it.findtext("link") or "").strip(), _iso(it.findtext("pubDate") or ""),
                                "rss", analyze_text(title + " " + (it.findtext("description") or "")[:300])))
        return out

    def fetch(self, source: str) -> list[NewsItem]:
        try:
            r = self.http.get(self.FEEDS[source])
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"{source}: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise ProviderUnavailable(f"{source}: HTTP {r.status_code}")
        return self.parse(r.text, source)


class CryptoPanic:
    URL = "https://cryptopanic.com/api/developer/v2/posts/"

    def __init__(self, http: httpx.Client | None = None, key: str | None = None):
        self.key = key or require_env("CRYPTOPANIC_API_KEY")["CRYPTOPANIC_API_KEY"]
        self.http = http or httpx.Client(timeout=10)

    @staticmethod
    def parse(raw: dict) -> list[NewsItem]:
        if "results" not in raw:
            raise ProviderUnavailable(f"cryptopanic: {raw.get('info') or raw.get('detail') or 'unexpected response'}")
        out = []
        for p in raw["results"]:
            votes = p.get("votes") or {}
            s = analyze_text(p.get("title", ""))
            pos, neg = votes.get("positive", 0) + votes.get("liked", 0), votes.get("negative", 0) + votes.get("disliked", 0)
            if pos + neg >= 5:  # enough community votes to override the lexicon label
                s["label"] = "bullish" if pos > 1.5 * neg else "bearish" if neg > 1.5 * pos else "neutral"
                s["votes_used"] = True
            src = (p.get("source") or {}).get("title") or (p.get("source") or {}).get("domain") or "cryptopanic"
            out.append(NewsItem(src, p.get("title", ""), p.get("original_url") or p.get("url", ""), p.get("published_at", ""),
                                "cryptopanic", s, votes or None))
        return out

    def fetch(self, currencies: str = "BTC,ETH", kind: str = "news") -> list[NewsItem]:
        try:
            r = self.http.get(self.URL, params={"auth_token": self.key, "public": "true", "currencies": currencies, "kind": kind})
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"cryptopanic: {type(e).__name__}: {e}") from e
        if r.status_code in (401, 403):
            raise ProviderUnavailable(f"cryptopanic: HTTP {r.status_code} (invalid API key)")
        return self.parse(r.json())


class Reddit:
    def __init__(self, http: httpx.Client | None = None):
        env = require_env("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")
        self.cid, self.secret, self.ua = env["REDDIT_CLIENT_ID"], env["REDDIT_CLIENT_SECRET"], env["REDDIT_USER_AGENT"]
        self.http = http or httpx.Client(timeout=10)
        self.token: str | None = None

    def _auth(self):
        r = self.http.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
                           auth=(self.cid, self.secret), headers={"User-Agent": self.ua})
        if r.status_code != 200 or "access_token" not in r.json():
            raise ProviderUnavailable(f"reddit: auth failed HTTP {r.status_code}")
        self.token = r.json()["access_token"]

    @staticmethod
    def parse(raw: dict, sub: str) -> list[NewsItem]:
        out = []
        for c in raw.get("data", {}).get("children", []):
            d = c["data"]
            from datetime import datetime, timezone
            out.append(NewsItem(f"reddit r/{sub}", d["title"], "https://www.reddit.com" + d["permalink"],
                                datetime.fromtimestamp(d["created_utc"], timezone.utc).isoformat(), "reddit",
                                analyze_text(d["title"]), {"score": d.get("score"), "comments": d.get("num_comments")}))
        return out

    def fetch(self, sub: str = "CryptoCurrency", limit: int = 50) -> list[NewsItem]:
        try:
            if not self.token:
                self._auth()
            r = self.http.get(f"https://oauth.reddit.com/r/{sub}/new", params={"limit": limit},
                              headers={"Authorization": f"Bearer {self.token}", "User-Agent": self.ua})
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"reddit: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise ProviderUnavailable(f"reddit: HTTP {r.status_code}")
        return self.parse(r.json(), sub)


def fear_greed(http: httpx.Client | None = None) -> dict:
    http = http or httpx.Client(timeout=10)
    try:
        r = http.get("https://api.alternative.me/fng/", params={"limit": 1})
        d = r.json()["data"][0]
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as e:
        raise ProviderUnavailable(f"fear-greed: {type(e).__name__}: {e}") from e
    return {"value": int(d["value"]), "classification": d["value_classification"], "timestamp": int(d["timestamp"]),
            "source": "alternative.me"}


def aggregate(items: list[NewsItem]) -> dict:
    """Sentiment summary per asset; counts only, no invented weights."""
    out: dict[str, dict] = {}
    for it in items:
        for a in it.sentiment.get("assets") or ["MARKET"]:
            d = out.setdefault(a, {"bullish": 0, "bearish": 0, "neutral": 0, "n": 0})
            d[it.sentiment["label"]] += 1
            d["n"] += 1
    for d in out.values():
        d["net"] = round((d["bullish"] - d["bearish"]) / d["n"], 3)
    return out


def collect() -> dict:
    """Pull every configured source; failures are listed per source, never filled in."""
    items, errors = [], {}
    rss = RSS()
    for src in RSS.FEEDS:
        try:
            items += rss.fetch(src)
        except ProviderUnavailable as e:
            errors[src] = str(e)
    ann = ExchangeAnnouncements()
    for name, factory in (("cryptopanic", lambda: CryptoPanic().fetch()), ("reddit", lambda: Reddit().fetch()),
                          ("bybit_announcements", lambda: ann.fetch("bybit")), ("okx_announcements", lambda: ann.fetch("okx"))):
        try:
            items += factory()
        except ProviderUnavailable as e:
            errors[name] = str(e)
    fg = None
    try:
        fg = fear_greed()
    except ProviderUnavailable as e:
        errors["fear_greed"] = str(e)
    items.sort(key=lambda i: i.published, reverse=True)
    return {"items": [i.as_dict() for i in items], "errors": errors, "fear_greed": fg, "sentiment": aggregate(items),
            "breaking": [i.as_dict() for i in items if set(i.sentiment["categories"]) & {"exchange_incident", "regulatory"}][:10]}


class ExchangeAnnouncements:
    """Official announcements from the exchanges that publish a documented public API:
    Bybit  GET https://api.bybit.com/v5/announcements/index?locale=en-US
    OKX    GET https://www.okx.com/api/v5/support/announcements
    Binance publishes no documented announcements API, so it is not included."""

    def __init__(self, http: httpx.Client | None = None):
        self.http = http or httpx.Client(timeout=10, headers={"User-Agent": "promovent/2.5"})

    @staticmethod
    def _iso_ms(ms) -> str:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).isoformat()

    @classmethod
    def parse_bybit(cls, raw: dict) -> list[NewsItem]:
        if raw.get("retCode") != 0:
            raise ProviderUnavailable(f"bybit announcements: {raw.get('retMsg')}")
        out = []
        for a in raw["result"].get("list", []):
            kind = (a.get("type") or {}).get("title", "")
            s = analyze_text(f"{a['title']} {a.get('description', '')[:200]} {kind}")
            out.append(NewsItem("Bybit announcement", a["title"], a.get("url", ""), cls._iso_ms(a["dateTimestamp"]),
                                "exchange", s, {"type": kind, "tags": a.get("tags", [])}))
        return out

    @classmethod
    def parse_okx(cls, raw: dict) -> list[NewsItem]:
        if str(raw.get("code")) != "0":
            raise ProviderUnavailable(f"okx announcements: {raw.get('msg')}")
        out = []
        for page in raw.get("data", []):
            for a in page.get("details", []):
                out.append(NewsItem("OKX announcement", a["title"], a.get("url", ""), cls._iso_ms(a["pTime"]), "exchange",
                                    analyze_text(f"{a['title']} {a.get('annType', '')}"), {"type": a.get("annType")}))
        return out

    def fetch(self, exchange: str) -> list[NewsItem]:
        url, params, parse = {
            "bybit": ("https://api.bybit.com/v5/announcements/index", {"locale": "en-US", "limit": 20}, self.parse_bybit),
            "okx": ("https://www.okx.com/api/v5/support/announcements", {}, self.parse_okx)}[exchange]
        try:
            r = self.http.get(url, params=params)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"{exchange} announcements: {type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise ProviderUnavailable(f"{exchange} announcements: HTTP {r.status_code}")
        return parse(r.json())
