"""Signed trading clients for Binance, Bybit and OKX spot markets (v1: spot only, long only).

Normalized results:
  Permissions(can_trade, withdrawals_enabled, detail)
  balances() -> {asset: (free, locked)}
  Rules(step, tick, min_qty, min_notional)  (from the exchange's instrument filters)
  OrderState(client_id, exchange_id, status, filled_qty, avg_price, raw)

Errors map to: AuthError (bad key/signature/IP), PermissionDenied, InsufficientBalance,
OrderNotFound, ExchangeRejected (other business errors), ExchangeUnavailable (network/5xx).
Every method sends a real HTTP request to the configured base URL; nothing here
returns a success the exchange did not send.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

import httpx

from . import signing


class ExecError(RuntimeError):
    code: str = "error"


class AuthError(ExecError):
    code = "auth"


class PermissionDenied(ExecError):
    code = "permission"


class InsufficientBalance(ExecError):
    code = "insufficient_balance"


class OrderNotFound(ExecError):
    code = "not_found"


class ExchangeRejected(ExecError):
    code = "rejected"


class ExchangeUnavailable(ExecError):
    code = "unavailable"


class MissingCredentials(ExecError):
    code = "missing_credentials"


FINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}


@dataclass
class Permissions:
    can_trade: bool
    withdrawals_enabled: bool | None  # None = could not be determined
    detail: dict = field(default_factory=dict)


@dataclass
class Rules:
    step: float
    tick: float
    min_qty: float
    min_notional: float

    def qty(self, q: float) -> float:
        d = Decimal(str(self.step))
        return float((Decimal(str(q)) / d).to_integral_value(ROUND_DOWN) * d)

    def price(self, p: float) -> float:
        d = Decimal(str(self.tick))
        return float((Decimal(str(p)) / d).to_integral_value(ROUND_HALF_UP) * d)


@dataclass
class OrderState:
    client_id: str
    exchange_id: str | None
    status: str
    filled_qty: float = 0.0
    avg_price: float | None = None
    raw: dict = field(default_factory=dict)

    @property
    def final(self) -> bool:
        return self.status in FINAL


def _fmt(x: float) -> str:
    s = f"{Decimal(str(x)):f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


@dataclass
class Credentials:
    api_key: str
    secret: str
    passphrase: str | None = None

    @classmethod
    def from_env(cls, exchange: str) -> "Credentials":
        p = f"PROMOVENT_{exchange.upper()}_"
        need = ["API_KEY", "API_SECRET"] + (["API_PASSPHRASE"] if exchange == "okx" else [])
        missing = [p + n for n in need if not os.getenv(p + n)]
        if missing:
            raise MissingCredentials(f"{exchange}: missing environment variables {', '.join(missing)}")
        return cls(os.environ[p + "API_KEY"], os.environ[p + "API_SECRET"], os.getenv(p + "API_PASSPHRASE"))

    def fingerprint(self) -> str:
        import hashlib
        return hashlib.sha256(self.api_key.encode()).hexdigest()[:16]

    def __repr__(self) -> str:  # never print secrets
        return f"Credentials(fingerprint={self.fingerprint()})"


class TradingClient:
    name = "base"
    MAINNET = TESTNET = ""

    def __init__(self, creds: Credentials, testnet: bool = True, client: httpx.Client | None = None,
                 base_url: str | None = None, recv_window_ms: int = 5000):
        self.creds, self.testnet = creds, testnet
        self.base = base_url or (self.TESTNET if testnet else self.MAINNET)
        self.http = client or httpx.Client(timeout=10.0)
        self.recv = recv_window_ms
        self._rules: dict[str, Rules] = {}

    def _send(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise ExchangeUnavailable(f"{self.name}: {type(e).__name__}: {e}") from e
        if r.status_code >= 500:
            raise ExchangeUnavailable(f"{self.name}: HTTP {r.status_code}")
        return r

    def rules(self, symbol: str) -> Rules:
        if symbol not in self._rules:
            self._rules[symbol] = self._fetch_rules(symbol)
        return self._rules[symbol]

    # interface
    def _fetch_rules(self, symbol: str) -> Rules: ...
    def permissions(self) -> Permissions: ...
    def balances(self) -> dict[str, tuple[float, float]]: ...
    def place(self, symbol: str, side: int, order_type: str, qty: float, client_id: str,
              price: float | None = None, stop_price: float | None = None) -> OrderState: ...
    def protect(self, symbol: str, qty: float, stop: float, target: float, client_id: str) -> list[OrderState]: ...
    def get(self, symbol: str, client_id: str) -> OrderState: ...
    def cancel(self, symbol: str, client_id: str) -> OrderState: ...
    def open_orders(self, symbol: str) -> list[OrderState]: ...


# ----------------------------------------------------------------------------- Binance
class BinanceTrading(TradingClient):
    name = "binance"
    MAINNET = "https://api.binance.com"
    TESTNET = "https://testnet.binance.vision"
    STATUS = {"NEW": "NEW", "PARTIALLY_FILLED": "PARTIALLY_FILLED", "FILLED": "FILLED", "CANCELED": "CANCELED",
              "PENDING_CANCEL": "NEW", "REJECTED": "REJECTED", "EXPIRED": "EXPIRED", "EXPIRED_IN_MATCH": "EXPIRED",
              "PENDING_NEW": "NEW"}

    @staticmethod
    def sym(symbol: str) -> str:
        return symbol.replace("/", "")

    time_offset_ms = 0
    used_weight = 0
    WEIGHT_LIMIT = 6000          # REQUEST_WEIGHT per minute (exchangeInfo rateLimits); we stop at 90 %

    def sync_time(self) -> int:
        """Binance rejects requests whose timestamp is outside recvWindow (-1021). Measure the offset to server time."""
        t0 = int(time.time() * 1000)
        r = self._send("GET", f"{self.base}/api/v3/time")
        t1 = int(time.time() * 1000)
        self.time_offset_ms = int(r.json()["serverTime"]) - (t0 + t1) // 2
        return self.time_offset_ms

    def _req(self, method: str, path: str, params: dict | None = None, signed: bool = True, _retry: bool = True):
        if self.used_weight >= 0.9 * self.WEIGHT_LIMIT:
            raise ExchangeUnavailable(f"binance: request weight {self.used_weight}/{self.WEIGHT_LIMIT} this minute; backing off")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {}
        if signed:
            params["recvWindow"] = self.recv
            params["timestamp"] = int(time.time() * 1000) + self.time_offset_ms
            q = urlencode(params)
            q += "&signature=" + signing.binance(self.creds.secret, q)
            headers["X-MBX-APIKEY"] = self.creds.api_key
        else:
            q = urlencode(params)
        r = self._send(method, f"{self.base}{path}?{q}" if q else f"{self.base}{path}", headers=headers)
        w = r.headers.get("x-mbx-used-weight-1m")
        if w and w.isdigit():
            self.used_weight = int(w)
        if r.status_code in (429, 418):
            ra = r.headers.get("retry-after", "?")
            raise ExchangeUnavailable(f"binance: HTTP {r.status_code} {'IP banned' if r.status_code == 418 else 'rate limited'}; "
                                      f"retry after {ra}s")
        try:
            body = r.json()
        except ValueError:
            raise ExchangeUnavailable(f"binance: non-JSON HTTP {r.status_code}") from None
        if isinstance(body, dict) and body.get("code") == -1021 and signed and _retry:
            self.sync_time()
            params.pop("signature", None)
            return self._req(method, path, {k: v for k, v in params.items() if k not in ("timestamp", "recvWindow")}, signed, False)
        if r.status_code != 200 or (isinstance(body, dict) and "code" in body and body.get("code", 0) < 0):
            self._raise(body if isinstance(body, dict) else {}, r.status_code)
        return body

    def fills(self, symbol: str, order_id: str) -> list[dict]:
        """Execution report per fill (price, qty, commission and its asset) from /api/v3/myTrades."""
        return [{"price": float(t["price"]), "qty": float(t["qty"]), "fee": float(t["commission"]), "fee_asset": t["commissionAsset"],
                 "trade_id": str(t["id"]), "maker": bool(t["isMaker"]), "ts": int(t["time"])}
                for t in self._req("GET", "/api/v3/myTrades", {"symbol": self.sym(symbol), "orderId": order_id})]

    def _raise(self, body: dict, status: int):
        code, msg = body.get("code"), body.get("msg", "")
        text = f"binance {code}: {msg}"
        if code in (-2014, -2015, -1022) or status == 401:
            raise AuthError(text + " (check API key, secret, IP whitelist and trading permission)")
        if code == -2010 and "insufficient" in msg.lower():
            raise InsufficientBalance(text)
        if code == -2013 or code == -2011 and "unknown order" in msg.lower():
            raise OrderNotFound(text)
        if status == 403 or status == 418 or status == 429:
            raise ExchangeUnavailable(text or f"HTTP {status} (rate limit or WAF)")
        raise ExchangeRejected(text)

    def _fetch_rules(self, symbol):
        info = self._req("GET", "/api/v3/exchangeInfo", {"symbol": self.sym(symbol)}, signed=False)
        f = {x["filterType"]: x for x in info["symbols"][0]["filters"]}
        notional = f.get("NOTIONAL", f.get("MIN_NOTIONAL", {})).get("minNotional", "0")
        return Rules(float(f["LOT_SIZE"]["stepSize"]), float(f["PRICE_FILTER"]["tickSize"]),
                     float(f["LOT_SIZE"]["minQty"]), float(notional))

    def permissions(self):
        acct = self._req("GET", "/api/v3/account", {"omitZeroBalances": "true"})
        wd, detail = None, {"account_permissions": acct.get("permissions")}
        try:
            rest = self._req("GET", "/sapi/v1/account/apiRestrictions")
            wd = bool(rest.get("enableWithdrawals"))
            detail["api_restrictions"] = {k: rest.get(k) for k in ("enableWithdrawals", "enableSpotAndMarginTrading", "ipRestrict")}
        except ExecError as e:
            detail["api_restrictions_error"] = str(e)  # endpoint does not exist on the spot testnet
        return Permissions(bool(acct.get("canTrade")), wd, detail)

    def balances(self):
        acct = self._req("GET", "/api/v3/account", {"omitZeroBalances": "true"})
        return {b["asset"]: (float(b["free"]), float(b["locked"])) for b in acct.get("balances", [])}

    def _state(self, o: dict, client_id: str | None = None) -> OrderState:
        filled = float(o.get("executedQty", 0) or 0)
        quote = float(o.get("cummulativeQuoteQty", 0) or 0)
        avg = quote / filled if filled > 0 and quote > 0 else None
        return OrderState(o.get("clientOrderId") or client_id or "", str(o.get("orderId")) if o.get("orderId") else None,
                          self.STATUS.get(o.get("status", ""), o.get("status", "UNKNOWN")), filled, avg, o)

    def place(self, symbol, side, order_type, qty, client_id, price=None, stop_price=None):
        p = {"symbol": self.sym(symbol), "side": "BUY" if side > 0 else "SELL", "quantity": _fmt(qty),
             "newClientOrderId": client_id, "newOrderRespType": "FULL"}
        if order_type == "market":
            p["type"] = "MARKET"
        elif order_type == "limit":
            p.update(type="LIMIT", timeInForce="GTC", price=_fmt(price))
        elif order_type in ("stop_loss", "take_profit"):
            p.update(type="STOP_LOSS_LIMIT" if order_type == "stop_loss" else "TAKE_PROFIT_LIMIT", timeInForce="GTC",
                     price=_fmt(price), stopPrice=_fmt(stop_price))
        else:
            raise ValueError(order_type)
        return self._state(self._req("POST", "/api/v3/order", p), client_id)

    def protect(self, symbol, qty, stop, target, client_id):
        r = self.rules(symbol)
        limit = r.price(stop * 0.995)  # stop-limit 0.5 % below trigger so it fills in a fast move
        o = self._req("POST", "/api/v3/orderList/oco", {
            "symbol": self.sym(symbol), "side": "SELL", "quantity": _fmt(qty), "listClientOrderId": client_id,
            "aboveType": "LIMIT_MAKER", "abovePrice": _fmt(r.price(target)), "aboveClientOrderId": client_id[:30] + "tp",
            "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": _fmt(r.price(stop)), "belowPrice": _fmt(limit),
            "belowTimeInForce": "GTC", "belowClientOrderId": client_id[:30] + "sl"})
        return [self._state(x) for x in o.get("orderReports", [])] or [OrderState(client_id, str(o.get("orderListId")), "NEW", raw=o)]

    def get(self, symbol, client_id):
        return self._state(self._req("GET", "/api/v3/order", {"symbol": self.sym(symbol), "origClientOrderId": client_id}), client_id)

    def cancel(self, symbol, client_id):
        return self._state(self._req("DELETE", "/api/v3/order", {"symbol": self.sym(symbol), "origClientOrderId": client_id}), client_id)

    def open_orders(self, symbol):
        return [self._state(o) for o in self._req("GET", "/api/v3/openOrders", {"symbol": self.sym(symbol)})]


# ----------------------------------------------------------------------------- Bybit
class BybitTrading(TradingClient):
    name = "bybit"
    MAINNET = "https://api.bybit.com"
    TESTNET = "https://api-testnet.bybit.com"
    STATUS = {"New": "NEW", "PartiallyFilled": "PARTIALLY_FILLED", "Filled": "FILLED", "Cancelled": "CANCELED",
              "PartiallyFilledCanceled": "CANCELED", "Rejected": "REJECTED", "Deactivated": "CANCELED",
              "Untriggered": "PENDING_TRIGGER", "Triggered": "NEW"}

    def _req(self, method: str, path: str, params: dict | None = None, signed: bool = True):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        ts, rw = str(int(time.time() * 1000)), str(self.recv)
        if method == "GET":
            payload = urlencode(params)
            url, body = (f"{self.base}{path}?{payload}" if payload else f"{self.base}{path}"), None
        else:
            payload = json.dumps(params, separators=(",", ":"))
            url, body = f"{self.base}{path}", payload
        headers = {"Content-Type": "application/json"}
        if signed:
            headers.update({"X-BAPI-API-KEY": self.creds.api_key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": rw,
                            "X-BAPI-SIGN": signing.bybit(self.creds.secret, ts, self.creds.api_key, rw, payload)})
        r = self._send(method, url, headers=headers, content=body)
        try:
            data = r.json()
        except ValueError:
            raise ExchangeUnavailable(f"bybit: non-JSON HTTP {r.status_code}") from None
        if r.status_code != 200 or data.get("retCode") != 0:
            self._raise(data, r.status_code)
        return data["result"]

    def _raise(self, d: dict, status: int):
        code, msg = d.get("retCode"), d.get("retMsg", "")
        text = f"bybit {code}: {msg}"
        if code in (10003, 10004, 33004) or status == 401:
            raise AuthError(text + " (check API key, secret and IP whitelist)")
        if code in (10005, 10024):
            raise PermissionDenied(text)
        if code in (170131, 110007, 110004, 170033):
            raise InsufficientBalance(text)
        if code in (170213, 110001):
            raise OrderNotFound(text)
        if code in (10006, 10018) or status in (403, 429):
            raise ExchangeUnavailable(text + " (rate limit)")
        raise ExchangeRejected(text)

    def _fetch_rules(self, symbol):
        d = self._req("GET", "/v5/market/instruments-info", {"category": "spot", "symbol": symbol.replace("/", "")}, signed=False)
        i = d["list"][0]
        lot, pf = i["lotSizeFilter"], i["priceFilter"]
        return Rules(float(lot["basePrecision"]), float(pf["tickSize"]), float(lot["minOrderQty"]), float(lot.get("minOrderAmt", 0)))

    def permissions(self):
        d = self._req("GET", "/v5/user/query-api")
        perms = d.get("permissions", {}) or {}
        flat = [p for v in perms.values() for p in (v or [])]
        can_trade = d.get("readOnly") == 0 and bool(perms.get("Spot"))
        return Permissions(can_trade, any("withdraw" in p.lower() for p in flat), {"readOnly": d.get("readOnly"), "permissions": perms})

    def balances(self):
        d = self._req("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        out = {}
        for c in (d.get("list") or [{}])[0].get("coin", []):
            total, locked = float(c.get("walletBalance") or 0), float(c.get("locked") or 0)
            out[c["coin"]] = (total - locked, locked)
        return out

    def _state(self, o: dict, client_id: str) -> OrderState:
        filled = float(o.get("cumExecQty") or 0)
        avg = float(o["avgPrice"]) if o.get("avgPrice") not in (None, "", "0") else None
        return OrderState(o.get("orderLinkId") or client_id, o.get("orderId"), self.STATUS.get(o.get("orderStatus", ""), "NEW"),
                          filled, avg, o)

    def place(self, symbol, side, order_type, qty, client_id, price=None, stop_price=None):
        p = {"category": "spot", "symbol": symbol.replace("/", ""), "side": "Buy" if side > 0 else "Sell", "qty": _fmt(qty),
             "orderLinkId": client_id}
        if order_type == "market":
            p.update(orderType="Market", marketUnit="baseCoin")
        elif order_type == "limit":
            p.update(orderType="Limit", price=_fmt(price), timeInForce="GTC")
        elif order_type in ("stop_loss", "take_profit"):
            p.update(orderType="Market", orderFilter="tpslOrder", triggerPrice=_fmt(stop_price), marketUnit="baseCoin")
        else:
            raise ValueError(order_type)
        r = self._req("POST", "/v5/order/create", p)
        return OrderState(r.get("orderLinkId", client_id), r.get("orderId"), "NEW", raw=r)

    def protect(self, symbol, qty, stop, target, client_id):
        # Bybit spot has no single-call OCO here: the stop is placed on the exchange; the take-profit is
        # watched by the engine (cancels the stop, then sells) so the same coins are never reserved twice.
        r = self.rules(symbol)
        return [self.place(symbol, -1, "stop_loss", qty, client_id[:30] + "sl", stop_price=r.price(stop))]

    def get(self, symbol, client_id):
        d = self._req("GET", "/v5/order/realtime", {"category": "spot", "orderLinkId": client_id})
        if not d.get("list"):
            d = self._req("GET", "/v5/order/history", {"category": "spot", "orderLinkId": client_id})
        if not d.get("list"):
            raise OrderNotFound(f"bybit: order {client_id} not found")
        return self._state(d["list"][0], client_id)

    def cancel(self, symbol, client_id):
        self._req("POST", "/v5/order/cancel", {"category": "spot", "symbol": symbol.replace("/", ""), "orderLinkId": client_id})
        return self.get(symbol, client_id)

    def open_orders(self, symbol):
        d = self._req("GET", "/v5/order/realtime", {"category": "spot", "symbol": symbol.replace("/", "")})
        return [self._state(o, o.get("orderLinkId", "")) for o in d.get("list", [])]


# ----------------------------------------------------------------------------- OKX
class OKXTrading(TradingClient):
    name = "okx"
    MAINNET = TESTNET = "https://www.okx.com"  # demo trading = same host + x-simulated-trading: 1
    STATUS = {"live": "NEW", "partially_filled": "PARTIALLY_FILLED", "filled": "FILLED", "canceled": "CANCELED",
              "mmp_canceled": "CANCELED", "effective": "NEW", "order_failed": "REJECTED", "pause": "NEW"}

    def __init__(self, creds, testnet=True, client=None, base_url=None, recv_window_ms=5000):
        if not creds.passphrase:
            raise MissingCredentials("okx: missing environment variable PROMOVENT_OKX_API_PASSPHRASE")
        super().__init__(creds, testnet, client, base_url, recv_window_ms)

    def _req(self, method: str, path: str, params: dict | None = None, signed: bool = True):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if method == "GET":
            q = urlencode(params)
            req_path, body = (f"{path}?{q}" if q else path), ""
        else:
            req_path, body = path, json.dumps(params, separators=(",", ":"))
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
        headers = {"Content-Type": "application/json"}
        if signed:
            headers.update({"OK-ACCESS-KEY": self.creds.api_key, "OK-ACCESS-TIMESTAMP": ts,
                            "OK-ACCESS-PASSPHRASE": self.creds.passphrase or "",
                            "OK-ACCESS-SIGN": signing.okx(self.creds.secret, ts, method, req_path, body)})
        if self.testnet:
            headers["x-simulated-trading"] = "1"
        r = self._send(method, f"{self.base}{req_path}", headers=headers, content=body or None)
        try:
            d = r.json()
        except ValueError:
            raise ExchangeUnavailable(f"okx: non-JSON HTTP {r.status_code}") from None
        if r.status_code != 200 or str(d.get("code")) != "0":
            self._raise(d, r.status_code)
        return d["data"]

    def _raise(self, d: dict, status: int):
        item = (d.get("data") or [{}])[0] if isinstance(d.get("data"), list) else {}
        code = str(item.get("sCode") or d.get("code"))
        msg = item.get("sMsg") or d.get("msg", "")
        text = f"okx {code}: {msg}"
        if code in ("50111", "50113", "50114", "50101", "50102", "50103", "50104", "50105") or status == 401:
            raise AuthError(text + " (check API key, secret, passphrase, demo/live mode and IP whitelist)")
        if code in ("50120", "50121"):
            raise PermissionDenied(text)
        if code in ("51008", "51127", "51131"):
            raise InsufficientBalance(text)
        if code in ("51603",):
            raise OrderNotFound(text)
        if code in ("50011", "50061") or status == 429:
            raise ExchangeUnavailable(text + " (rate limit)")
        raise ExchangeRejected(text)

    def _fetch_rules(self, symbol):
        i = self._req("GET", "/api/v5/public/instruments", {"instType": "SPOT", "instId": symbol.replace("/", "-")}, signed=False)[0]
        return Rules(float(i["lotSz"]), float(i["tickSz"]), float(i["minSz"]), 0.0)

    def permissions(self):
        c = self._req("GET", "/api/v5/account/config")[0]
        perm = [p.strip() for p in c.get("perm", "").split(",") if p.strip()]
        return Permissions("trade" in perm, "withdraw" in perm, {"perm": perm, "acctLv": c.get("acctLv")})

    def balances(self):
        d = self._req("GET", "/api/v5/account/balance")[0]
        return {x["ccy"]: (float(x.get("availBal") or 0), float(x.get("frozenBal") or 0)) for x in d.get("details", [])}

    def _state(self, o: dict, client_id: str) -> OrderState:
        filled = float(o.get("accFillSz") or 0)
        avg = float(o["avgPx"]) if o.get("avgPx") not in (None, "", "0") else None
        return OrderState(o.get("clOrdId") or client_id, o.get("ordId"), self.STATUS.get(o.get("state", ""), "NEW"), filled, avg, o)

    def place(self, symbol, side, order_type, qty, client_id, price=None, stop_price=None):
        p = {"instId": symbol.replace("/", "-"), "tdMode": "cash", "clOrdId": client_id, "side": "buy" if side > 0 else "sell",
             "sz": _fmt(qty)}
        if order_type == "market":
            p.update(ordType="market", tgtCcy="base_ccy")
        elif order_type == "limit":
            p.update(ordType="limit", px=_fmt(price))
        else:
            raise ValueError(f"okx: use protect() for {order_type}")
        d = self._req("POST", "/api/v5/trade/order", p)[0]
        return OrderState(d.get("clOrdId", client_id), d.get("ordId"), "NEW", raw=d)

    def protect(self, symbol, qty, stop, target, client_id):
        r = self.rules(symbol)
        d = self._req("POST", "/api/v5/trade/order-algo", {
            "instId": symbol.replace("/", "-"), "tdMode": "cash", "side": "sell", "ordType": "oco", "sz": _fmt(qty),
            "algoClOrdId": client_id, "tpTriggerPx": _fmt(r.price(target)), "tpOrdPx": "-1",
            "slTriggerPx": _fmt(r.price(stop)), "slOrdPx": "-1"})[0]
        return [OrderState(d.get("algoClOrdId", client_id), d.get("algoId"), "PENDING_TRIGGER", raw=d)]

    def get(self, symbol, client_id):
        d = self._req("GET", "/api/v5/trade/order", {"instId": symbol.replace("/", "-"), "clOrdId": client_id})
        if not d:
            raise OrderNotFound(f"okx: order {client_id} not found")
        return self._state(d[0], client_id)

    def cancel(self, symbol, client_id):
        self._req("POST", "/api/v5/trade/cancel-order", {"instId": symbol.replace("/", "-"), "clOrdId": client_id})
        return self.get(symbol, client_id)

    def open_orders(self, symbol):
        return [self._state(o, o.get("clOrdId", "")) for o in
                self._req("GET", "/api/v5/trade/orders-pending", {"instType": "SPOT", "instId": symbol.replace("/", "-")})]


CLIENTS = {"binance": BinanceTrading, "bybit": BybitTrading, "okx": OKXTrading}


def client_from_env(exchange: str, testnet: bool | None = None, http: httpx.Client | None = None) -> TradingClient:
    if exchange not in CLIENTS:
        raise ExecError(f"no trading client for {exchange!r}; one of {sorted(CLIENTS)}")
    if testnet is None:
        testnet = os.getenv("PROMOVENT_EXCHANGE_TESTNET", "yes").lower() != "no"
    return CLIENTS[exchange](Credentials.from_env(exchange), testnet=testnet, client=http)


def isclose(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
