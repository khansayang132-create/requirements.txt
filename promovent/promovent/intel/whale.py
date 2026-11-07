"""Whale intelligence.

Providers
- Whale Alert  (GET https://api.whale-alert.io/v1/transactions, key WHALE_ALERT_API_KEY): multi-chain
  transfers with owner attribution (exchange / unknown).
- Blockchair   (GET https://api.blockchair.com/{bitcoin|ethereum}/transactions, optional BLOCKCHAIR_API_KEY):
  largest recent transactions by USD value. No owner attribution, so every Blockchair item is a
  plain `transfer`; it is never reported as an exchange flow.
- Etherscan    (GET https://api.etherscan.io/v2/api, key ETHERSCAN_API_KEY): large ETH / ERC-20 transfers
  for addresses YOU list in PROMOVENT_WATCH_ADDRESSES (label:chain:address,...). No exchange
  address list is built in: a wrong label would invent flows.

Classification (never "buy" or "sell"; a transfer is not a trade):
  exchange_inflow   unknown -> exchange     (coins moved onto an exchange; possible sell intent, unconfirmed)
  exchange_outflow  exchange -> unknown     (coins left an exchange; possible custody, unconfirmed)
  exchange_internal exchange -> same exchange / exchange -> exchange
  transfer          unknown -> unknown
  mint / burn       issuer events (stablecoins)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

import httpx
import numpy as np

from . import ProviderUnavailable, require_env

EXPLORERS = {"ethereum": "https://etherscan.io/tx/", "bitcoin": "https://www.blockchain.com/explorer/transactions/btc/",
             "tron": "https://tronscan.org/#/transaction/", "solana": "https://solscan.io/tx/", "ripple": "https://xrpscan.com/tx/",
             "binancechain": "https://bscscan.com/tx/", "polygon": "https://polygonscan.com/tx/"}


@dataclass
class WhaleTx:
    provider: str
    chain: str
    tx_hash: str
    ts: int
    asset: str
    amount: float
    amount_usd: float | None
    from_owner: str
    from_type: str
    to_owner: str
    to_type: str
    flow: str = ""
    reference: str = ""
    note: str = "on-chain transfer; not a confirmed trade"

    def as_dict(self):
        return self.__dict__.copy()


def classify(from_type: str, to_type: str, from_owner: str, to_owner: str, tx_type: str = "transfer") -> str:
    if tx_type in ("mint", "burn"):
        return tx_type
    fe, te = from_type == "exchange", to_type == "exchange"
    if fe and te:
        return "exchange_internal"
    if te:
        return "exchange_inflow"
    if fe:
        return "exchange_outflow"
    return "transfer"


class WhaleAlert:
    URL = "https://api.whale-alert.io/v1/transactions"

    def __init__(self, http: httpx.Client | None = None, api_key: str | None = None):
        self.key = api_key or require_env("WHALE_ALERT_API_KEY")["WHALE_ALERT_API_KEY"]
        self.http = http or httpx.Client(timeout=10)

    @staticmethod
    def parse(raw: dict) -> list[WhaleTx]:
        if raw.get("result") != "success":
            raise ProviderUnavailable(f"whale-alert: {raw.get('message', raw.get('result'))}")
        out = []
        for t in raw.get("transactions", []):
            f, to = t.get("from", {}), t.get("to", {})
            tx = WhaleTx("whale-alert", t["blockchain"], t["hash"], int(t["timestamp"]), t["symbol"].upper(), float(t["amount"]),
                         float(t["amount_usd"]) if t.get("amount_usd") is not None else None,
                         f.get("owner") or "unknown", f.get("owner_type", "unknown"), to.get("owner") or "unknown",
                         to.get("owner_type", "unknown"))
            tx.flow = classify(tx.from_type, tx.to_type, tx.from_owner, tx.to_owner, t.get("transaction_type", "transfer"))
            tx.reference = EXPLORERS.get(tx.chain, "") + tx.tx_hash if tx.chain in EXPLORERS else ""
            out.append(tx)
        return out

    def recent(self, min_value_usd: int = 1_000_000, since_s: int = 3600) -> list[WhaleTx]:
        try:
            r = self.http.get(self.URL, params={"api_key": self.key, "min_value": min_value_usd,
                                                "start": int(time.time()) - since_s, "limit": 100})
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"whale-alert: {type(e).__name__}: {e}") from e
        if r.status_code in (401, 403):
            raise ProviderUnavailable(f"whale-alert: HTTP {r.status_code} (invalid key or plan)")
        if r.status_code == 429:
            raise ProviderUnavailable("whale-alert: rate limited (HTTP 429)")
        return self.parse(r.json())


@dataclass
class Watch:
    label: str
    owner_type: str   # exchange | fund | unknown
    address: str


class Etherscan:
    URL = "https://api.etherscan.io/v2/api"

    def __init__(self, http: httpx.Client | None = None, api_key: str | None = None, watch: list[Watch] | None = None):
        self.key = api_key or require_env("ETHERSCAN_API_KEY")["ETHERSCAN_API_KEY"]
        self.http = http or httpx.Client(timeout=10)
        self.watch = watch if watch is not None else self.watch_from_env()

    @staticmethod
    def watch_from_env() -> list[Watch]:
        out = []
        for item in filter(None, os.getenv("PROMOVENT_WATCH_ADDRESSES", "").split(",")):
            label, kind, addr = item.split(":")
            out.append(Watch(label, kind, addr.lower()))
        return out

    def parse(self, raw: dict, w: Watch, min_eth: float) -> list[WhaleTx]:
        if raw.get("status") != "1":
            if raw.get("message") == "No transactions found":
                return []
            raise ProviderUnavailable(f"etherscan: {raw.get('message')}: {raw.get('result')}")
        out = []
        for t in raw["result"]:
            amt = int(t["value"]) / 1e18
            if amt < min_eth or t.get("isError") == "1":
                continue
            inbound = t["to"].lower() == w.address
            ftype, ttype = ("unknown", w.owner_type) if inbound else (w.owner_type, "unknown")
            fown, town = ("unknown", w.label) if inbound else (w.label, "unknown")
            tx = WhaleTx("etherscan", "ethereum", t["hash"], int(t["timeStamp"]), "ETH", amt, None, fown, ftype, town, ttype)
            tx.flow = classify(ftype, ttype, fown, town)
            tx.reference = EXPLORERS["ethereum"] + t["hash"]
            out.append(tx)
        return out

    def recent(self, min_eth: float = 500) -> list[WhaleTx]:
        if not self.watch:
            raise ProviderUnavailable("etherscan: PROMOVENT_WATCH_ADDRESSES is empty (label:owner_type:address,...)")
        out = []
        for w in self.watch:
            try:
                r = self.http.get(self.URL, params={"chainid": 1, "module": "account", "action": "txlist", "address": w.address,
                                                    "sort": "desc", "page": 1, "offset": 100, "apikey": self.key})
            except httpx.HTTPError as e:
                raise ProviderUnavailable(f"etherscan: {type(e).__name__}: {e}") from e
            out += self.parse(r.json(), w, min_eth)
        return out


@dataclass
class WhaleSummary:
    txs: list[WhaleTx] = field(default_factory=list)

    def flows(self) -> dict:
        by: dict[str, dict] = {}
        for t in self.txs:
            a = by.setdefault(t.asset, {"exchange_inflow_usd": 0.0, "exchange_outflow_usd": 0.0, "transfer_usd": 0.0, "count": 0})
            usd = t.amount_usd or 0.0
            key = {"exchange_inflow": "exchange_inflow_usd", "exchange_outflow": "exchange_outflow_usd"}.get(t.flow, "transfer_usd")
            a[key] += usd
            a["count"] += 1
        for a in by.values():
            a["net_exchange_flow_usd"] = a["exchange_inflow_usd"] - a["exchange_outflow_usd"]
        return by

    def clusters(self, window_s: int = 900, min_size: int = 3) -> list[dict]:
        """Groups of >= min_size large transfers of one asset within window_s seconds."""
        out = []
        for asset in {t.asset for t in self.txs}:
            ts = sorted((t for t in self.txs if t.asset == asset), key=lambda t: t.ts)
            i = 0
            for j in range(len(ts)):
                while ts[j].ts - ts[i].ts > window_s:
                    i += 1
                if j - i + 1 >= min_size and (not out or out[-1]["asset"] != asset or out[-1]["end"] < ts[i].ts):
                    grp = ts[i:j + 1]
                    out.append({"asset": asset, "start": grp[0].ts, "end": grp[-1].ts, "count": len(grp),
                                "usd": sum(t.amount_usd or 0 for t in grp), "hashes": [t.tx_hash for t in grp]})
                elif j - i + 1 >= min_size:
                    grp = ts[i:j + 1]
                    out[-1].update(end=grp[-1].ts, count=len(grp), usd=sum(t.amount_usd or 0 for t in grp),
                                   hashes=[t.tx_hash for t in grp])
        return out

    def unusual(self, history_usd: dict[str, list[float]], z: float = 3.0) -> list[dict]:
        """Assets whose current total transfer value is z std above their own history."""
        out = []
        for asset, f in self.flows().items():
            h = np.array(history_usd.get(asset, []), float)
            if len(h) < 10:
                continue
            cur = f["exchange_inflow_usd"] + f["exchange_outflow_usd"] + f["transfer_usd"]
            sd = h.std()
            if sd > 0 and (cur - h.mean()) / sd >= z:
                out.append({"asset": asset, "current_usd": cur, "zscore": float((cur - h.mean()) / sd)})
        return out


class Blockchair:
    URL = "https://api.blockchair.com/{chain}/transactions"
    CHAINS = {"bitcoin": "BTC", "ethereum": "ETH"}

    def __init__(self, http: httpx.Client | None = None, api_key: str | None = None):
        self.key = api_key if api_key is not None else os.getenv("BLOCKCHAIR_API_KEY", "")
        self.http = http or httpx.Client(timeout=10)

    @classmethod
    def parse(cls, raw: dict, chain: str) -> list[WhaleTx]:
        ctx = raw.get("context", {})
        if ctx.get("code") != 200:
            raise ProviderUnavailable(f"blockchair: {ctx.get('error') or ctx.get('code')}")
        from datetime import datetime, timezone
        out = []
        for t in raw.get("data", []):
            ts = int(datetime.strptime(t["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
            raw_amount = float(t.get("output_total") if chain == "bitcoin" else t.get("value", 0))
            amount = raw_amount / (1e8 if chain == "bitcoin" else 1e18)
            usd = t.get("output_total_usd") if chain == "bitcoin" else t.get("value_usd")
            tx = WhaleTx("blockchair", chain, t["hash"], ts, cls.CHAINS[chain], amount, float(usd) if usd is not None else None,
                         "unknown", "unknown", "unknown", "unknown", flow="transfer", reference=EXPLORERS[chain] + t["hash"])
            out.append(tx)
        return out

    def recent(self, chain: str = "bitcoin", min_usd: int = 1_000_000) -> list[WhaleTx]:
        field = "output_total_usd" if chain == "bitcoin" else "value_usd"
        params = {"q": f"{field}({min_usd}..)", "s": "id(desc)", "limit": 50}
        if self.key:
            params["key"] = self.key
        try:
            r = self.http.get(self.URL.format(chain=chain), params=params)
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"blockchair: {type(e).__name__}: {e}") from e
        if r.status_code in (402, 429, 430):
            raise ProviderUnavailable(f"blockchair: HTTP {r.status_code} (rate limit or plan; set BLOCKCHAIR_API_KEY)")
        return self.parse(r.json(), chain)
