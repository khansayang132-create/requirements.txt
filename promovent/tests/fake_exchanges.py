"""In-process fake exchanges for execution tests (httpx.MockTransport).

FakeBinance verifies every signed request's HMAC exactly as Binance would and keeps
balances and orders, so the client's signing, parameter encoding, error mapping and
the engine's flows are exercised end to end. It is a test double: passing here is
not evidence that a real exchange accepted an order.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import parse_qsl, urlsplit

import httpx

KEY, SECRET = "testkey" * 4, "testsecret" * 4


class FakeBinance:
    def __init__(self, usdt=10_000.0, price=100.0, can_trade=True, withdrawals=False, fill_mode="full",
                 sapi=True, oco_fails=False):
        self.bal = {"USDT": [usdt, 0.0], "BTC": [0.0, 0.0]}
        self.price, self.can_trade, self.withdrawals, self.fill_mode, self.sapi = price, can_trade, withdrawals, fill_mode, sapi
        self.oco_fails = oco_fails
        self.orders: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.next_id = 1
        self.clock_skew_ms = 0

    def server_time(self):
        import time as _t
        return int(_t.time() * 1000) + self.clock_skew_ms

    def transport(self):
        return httpx.MockTransport(self.handle)

    def err(self, code, msg, status=400):
        return httpx.Response(status, json={"code": code, "msg": msg})

    def handle(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        u = urlsplit(str(req.url))
        path, query = u.path, u.query
        params = dict(parse_qsl(query, keep_blank_values=True))
        if path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": self.server_time()})
        if path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json={"symbols": [{"symbol": params["symbol"], "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001"},
                {"filterType": "NOTIONAL", "minNotional": "5"}]}]})
        # signed endpoints
        if req.headers.get("X-MBX-APIKEY") != KEY:
            return self.err(-2015, "Invalid API-key, IP, or permissions for action.", 401)
        unsigned, _, sig = query.rpartition("&signature=")
        if hmac.new(SECRET.encode(), unsigned.encode(), hashlib.sha256).hexdigest() != sig:
            return self.err(-1022, "Signature for this request is not valid.", 400)
        if abs(int(params["timestamp"]) - self.server_time()) > int(params.get("recvWindow", 5000)):
            return self.err(-1021, "Timestamp for this request is outside of the recvWindow.")
        if path == "/api/v3/myTrades":
            o = next((o for o in self.orders.values() if str(o["orderId"]) == params["orderId"]), None)
            if not o or float(o["executedQty"]) == 0:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"id": 1, "price": str(self.price), "qty": o["executedQty"],
                                              "commission": str(float(o["executedQty"]) * 0.001), "commissionAsset": "BTC",
                                              "time": self.server_time(), "isMaker": False}])
        if path == "/api/v3/account":
            return httpx.Response(200, json={"canTrade": self.can_trade, "permissions": ["SPOT"],
                                             "balances": [{"asset": a, "free": str(f), "locked": str(lk)} for a, (f, lk) in self.bal.items()]})
        if path == "/sapi/v1/account/apiRestrictions":
            if not self.sapi:
                return httpx.Response(404, text="")
            return httpx.Response(200, json={"enableWithdrawals": self.withdrawals, "enableSpotAndMarginTrading": True,
                                             "ipRestrict": True})
        if path == "/api/v3/order" and req.method == "POST":
            return self.new_order(params)
        if path == "/api/v3/order" and req.method == "GET":
            o = self.orders.get(params["origClientOrderId"])
            return httpx.Response(200, json=o) if o else self.err(-2013, "Order does not exist.")
        if path == "/api/v3/order" and req.method == "DELETE":
            o = self.orders.get(params["origClientOrderId"])
            if not o:
                return self.err(-2011, "Unknown order sent.")
            o["status"] = "CANCELED"
            return httpx.Response(200, json=o)
        if path == "/api/v3/openOrders":
            return httpx.Response(200, json=[o for o in self.orders.values() if o["status"] in ("NEW", "PARTIALLY_FILLED")])
        if path == "/api/v3/orderList/oco":
            if self.oco_fails:
                return self.err(-1013, "Filter failure: PERCENT_PRICE_BY_SIDE")
            reports = []
            for leg in ("above", "below"):
                cid = params[f"{leg}ClientOrderId"]
                o = {"clientOrderId": cid, "orderId": self.next_id, "status": "NEW", "executedQty": "0",
                     "cummulativeQuoteQty": "0", "type": params[f"{leg}Type"]}
                self.next_id += 1
                self.orders[cid] = o
                reports.append(o)
            return httpx.Response(200, json={"orderListId": 9, "listClientOrderId": params["listClientOrderId"], "orderReports": reports})
        return httpx.Response(404, json={"code": -1, "msg": f"no fake for {path}"})

    def new_order(self, p):
        cid = p["newClientOrderId"]
        if cid in self.orders:
            return self.err(-2010, "Duplicate order sent.")
        qty = float(p["quantity"])
        if p["side"] == "BUY" and qty * self.price > self.bal["USDT"][0]:
            return self.err(-2010, "Account has insufficient balance for requested action.")
        if p["side"] == "SELL" and qty > self.bal["BTC"][0] + 1e-12:
            return self.err(-2010, "Account has insufficient balance for requested action.")
        filled = {"full": qty, "partial": round(qty / 2, 5), "none": 0.0}[self.fill_mode] if p["type"] == "MARKET" else 0.0
        status = "FILLED" if filled == qty else ("PARTIALLY_FILLED" if filled > 0 else "NEW")
        sign = 1 if p["side"] == "BUY" else -1
        self.bal["USDT"][0] -= sign * filled * self.price
        self.bal["BTC"][0] += sign * filled
        o = {"clientOrderId": cid, "orderId": self.next_id, "status": status, "executedQty": str(filled),
             "cummulativeQuoteQty": str(filled * self.price), "type": p["type"], "side": p["side"]}
        self.next_id += 1
        self.orders[cid] = o
        return httpx.Response(200, json=o)


def ok_bybit(result):
    return {"retCode": 0, "retMsg": "OK", "result": result}


def verify_bybit(req: httpx.Request) -> bool:
    payload = urlsplit(str(req.url)).query if req.method == "GET" else req.content.decode()
    h = req.headers
    want = hmac.new(SECRET.encode(), f"{h['X-BAPI-TIMESTAMP']}{KEY}{h['X-BAPI-RECV-WINDOW']}{payload}".encode(), hashlib.sha256).hexdigest()
    return h.get("X-BAPI-API-KEY") == KEY and h.get("X-BAPI-SIGN") == want


def verify_okx(req: httpx.Request, passphrase: str) -> bool:
    u = urlsplit(str(req.url))
    path = u.path + (f"?{u.query}" if u.query else "")
    h = req.headers
    msg = f"{h['OK-ACCESS-TIMESTAMP']}{req.method}{path}{req.content.decode() if req.content else ''}"
    want = base64.b64encode(hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return h.get("OK-ACCESS-KEY") == KEY and h.get("OK-ACCESS-SIGN") == want and h.get("OK-ACCESS-PASSPHRASE") == passphrase


def body(req):
    return json.loads(req.content) if req.content else {}
