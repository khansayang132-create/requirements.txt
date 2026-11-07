"""Dynamic asset universe: the core list plus the most liquid USDT spot pairs the exchange actually lists."""
from __future__ import annotations

import httpx

CORE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT", "LINK/USDT", "AVAX/USDT"]
STABLE = {"USDC", "USDT", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDG", "EUR", "EURT", "XAUT", "PAXG"}


def parse_okx_tickers(raw: dict) -> list[dict]:
    if str(raw.get("code")) != "0":
        raise ValueError(f"okx tickers: {raw.get('msg')}")
    out = []
    for t in raw["data"]:
        base, quote = t["instId"].split("-")[:2]
        if quote != "USDT" or base in STABLE:
            continue
        last, vol_ccy = float(t.get("last") or 0), float(t.get("volCcy24h") or 0)  # volCcy24h = quote volume for SPOT
        if last <= 0:
            continue
        bid, ask = float(t.get("bidPx") or 0), float(t.get("askPx") or 0)
        spread = (ask - bid) / ((ask + bid) / 2) * 1e4 if bid > 0 and ask > 0 else None
        out.append({"symbol": f"{base}/USDT", "quote_volume_24h": vol_ccy, "spread_bps": spread, "last": last})
    return sorted(out, key=lambda r: -r["quote_volume_24h"])


def build(tickers: list[dict], min_quote_volume: float = 20e6, max_spread_bps: float = 10.0, extra: int = 5) -> dict:
    listed = {t["symbol"]: t for t in tickers}
    core = [s for s in CORE if s in listed]
    unavailable = [s for s in CORE if s not in listed]
    added = [t["symbol"] for t in tickers if t["symbol"] not in core and t["quote_volume_24h"] >= min_quote_volume
             and (t["spread_bps"] is None or t["spread_bps"] <= max_spread_bps)][:extra]
    return {"symbols": core + added, "core": core, "added_by_liquidity": added, "core_not_listed": unavailable,
            "rule": f"core list + top {extra} USDT spot pairs with 24h volume >= ${min_quote_volume:,.0f} and spread <= {max_spread_bps} bps"}


def okx_universe(http: httpx.Client | None = None, **kw) -> dict:
    http = http or httpx.Client(timeout=10)
    r = http.get("https://www.okx.com/api/v5/market/tickers", params={"instType": "SPOT"})
    return build(parse_okx_tickers(r.json()), **kw)
