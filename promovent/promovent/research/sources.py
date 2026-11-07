"""Extra public data used by research (OKX derivatives statistics, Fear & Greed history). No keys needed."""
from __future__ import annotations

import time

import httpx
import pandas as pd

OKX = "https://www.okx.com"


class SourceError(RuntimeError):
    pass


def _get(http: httpx.Client, url: str, params: dict) -> dict:
    try:
        r = http.get(url, params=params)
    except httpx.HTTPError as e:
        raise SourceError(f"{url}: {type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise SourceError(f"{url}: HTTP {r.status_code}")
    return r.json()


def okx_funding_history(http: httpx.Client, inst: str = "BTC-USDT-SWAP", pages: int = 10) -> pd.Series:
    """GET /api/v5/public/funding-rate-history (100 per page, paged with `after`). Realized 8h funding rates."""
    rows, after = [], None
    for _ in range(pages):
        d = _get(http, OKX + "/api/v5/public/funding-rate-history", {"instId": inst, "limit": 100, **({"after": after} if after else {})})
        if str(d.get("code")) != "0":
            raise SourceError(f"okx funding history: {d.get('msg')}")
        if not d["data"]:
            break
        rows += d["data"]
        after = d["data"][-1]["fundingTime"]
        time.sleep(0.25)
    if not rows:
        raise SourceError("okx funding history: empty")
    s = pd.Series({pd.Timestamp(int(r["fundingTime"]), unit="ms", tz="UTC"): float(r.get("realizedRate") or r["fundingRate"]) for r in rows})
    return s.sort_index()


def okx_open_interest_history(http: httpx.Client, ccy: str = "BTC", period: str = "1D") -> pd.DataFrame:
    """GET /api/v5/rubik/stat/contracts/open-interest-volume: daily open interest and volume (USD)."""
    d = _get(http, OKX + "/api/v5/rubik/stat/contracts/open-interest-volume", {"ccy": ccy, "period": period})
    if str(d.get("code")) != "0":
        raise SourceError(f"okx OI history: {d.get('msg')}")
    df = pd.DataFrame(d["data"], columns=["ts", "oi_usd", "vol_usd"]).astype(float)
    df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    return df.sort_index()


def okx_liquidations(http: httpx.Client, uly: str = "BTC-USDT") -> list[dict]:
    """GET /api/v5/public/liquidation-orders (recent filled liquidations of perpetual swaps)."""
    d = _get(http, OKX + "/api/v5/public/liquidation-orders", {"instType": "SWAP", "uly": uly, "state": "filled"})
    if str(d.get("code")) != "0":
        raise SourceError(f"okx liquidations: {d.get('msg')}")
    out = []
    for g in d["data"]:
        for x in g.get("details", []):
            out.append({"ts": int(x["ts"]), "side": x["side"], "pos_side": x.get("posSide"), "price": float(x["bkPx"]),
                        "size": float(x["sz"])})
    return out


def fear_greed_history(http: httpx.Client, days: int = 400) -> pd.Series:
    d = _get(http, "https://api.alternative.me/fng/", {"limit": days})
    if "data" not in d:
        raise SourceError("alternative.me: no data")
    return pd.Series({pd.Timestamp(int(x["timestamp"]), unit="s", tz="UTC"): int(x["value"]) for x in d["data"]}).sort_index()
