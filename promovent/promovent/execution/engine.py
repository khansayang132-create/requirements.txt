"""Central live execution engine (modes 4 and 5).

Order of checks before ANY live order (`preflight`), each reported by name:
  mode                live mode selected and PROMOVENT_ENABLE_LIVE=yes
  autonomy            mode 5 only: autonomous trading activated, symbol/strategy allowed, per-order cap
  kill_switch         kill switch off; daily/weekly/drawdown lockouts not hit (risk engine)
  strategy            strategy passed the validation gate
  long_only           spot account: short signals are refused (no margin borrowing)
  stop_loss           stop present, below entry for longs; target above entry
  market_data         price newer than max_data_age_s
  connection          exchange reachable, key valid (permissions call succeeds)
  permissions         key can trade; key must NOT allow withdrawals (unknown is refused on mainnet)
  risk                RiskEngine sizes the order and approves it
  exchange_rules      size rounded to lot step, at/above min qty and min notional
  balance             free quote balance covers notional + fee buffer
  duplicate           client order id unused locally and unknown to the exchange
Any failure stops the order and the reason is returned verbatim.

Mode 4 (assisted): `propose()` runs preflight and returns a confirmation token valid for
`confirm_ttl_s`. Nothing is sent until `confirm(token)`, which runs preflight again.
Mode 5 (autonomous): `execute()` runs preflight and sends, only while `autonomy.active`.

After the entry is acknowledged the engine polls status. Partial fills are protected
for the filled quantity and the remainder is cancelled after `fill_timeout_s`. If the
protective order cannot be placed, the position is closed at market, the kill switch is
engaged, and a critical risk event is recorded.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..config import Settings
from ..db import Store
from ..models import Signal
from ..risk import RiskEngine, RiskState
from .clients import (ExecError, InsufficientBalance, OrderNotFound, OrderState, Permissions, TradingClient)


class Autonomy(BaseModel):
    """Mode 5 permissions. Set only by an admin through /api/live/autonomy."""
    active: bool = False
    allowed_symbols: list[str] = Field(default_factory=list)
    allowed_strategies: list[str] = Field(default_factory=list)
    max_order_notional: float = Field(100.0, gt=0)
    max_orders_per_day: int = Field(5, ge=1, le=100)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Preflight:
    checks: list[Check] = field(default_factory=list)
    qty: float = 0.0
    price: float = 0.0
    risk_amount: float = 0.0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def fail(self, name: str, detail: str) -> "Preflight":
        self.checks.append(Check(name, False, detail))
        return self

    def passed(self, name: str, detail: str = "") -> None:
        self.checks.append(Check(name, True, detail))

    def as_dict(self) -> dict:
        return {"ok": self.ok, "qty": self.qty, "price": self.price, "risk_amount": self.risk_amount,
                "checks": [c.__dict__ for c in self.checks],
                "failed": [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]}


class LiveOrderRejected(RuntimeError):
    def __init__(self, pf: Preflight | None, msg: str | None = None):
        self.preflight = pf
        super().__init__(msg or "; ".join(pf.as_dict()["failed"]) if pf else msg)


@dataclass
class Pending:
    token: str
    signal: Signal
    expires: float
    preflight: Preflight
    actor: str


class LiveExecutionEngine:
    def __init__(self, settings: Settings, risk: RiskEngine, store: Store, client: TradingClient,
                 validated: set[str], state: RiskState, autonomy: Autonomy | None = None,
                 fee_buffer: float = 0.002, max_data_age_s: float = 90, confirm_ttl_s: float = 120,
                 fill_timeout_s: float = 30, poll_s: float = 1.0, sleep=time.sleep, now=time.time):
        self.settings, self.risk, self.store, self.client = settings, risk, store, client
        self.validated, self.state = validated, state
        self.autonomy = autonomy or Autonomy()
        self.fee_buffer, self.max_age, self.ttl = fee_buffer, max_data_age_s, confirm_ttl_s
        self.fill_timeout, self.poll_s, self.sleep, self.now = fill_timeout_s, poll_s, sleep, now
        self.pending: dict[str, Pending] = {}
        self._perm_cache: tuple[float, Permissions] | None = None

    @property
    def venue(self) -> str:
        return self.client.name

    # ------------------------------------------------------------------ checks
    def permissions(self, max_age: float = 60) -> Permissions:
        if self._perm_cache and self.now() - self._perm_cache[0] < max_age:
            return self._perm_cache[1]
        p = self.client.permissions()
        self._perm_cache = (self.now(), p)
        return p

    def preflight(self, sig: Signal, price: float, price_ts: float, correlations: dict | None = None) -> Preflight:
        pf, mode = Preflight(price=price), self.settings.mode
        if not mode.is_live:
            return pf.fail("mode", f"mode is {mode.value}; live orders need assisted_live or autonomous_live")
        if not self.settings.live_trading_enabled:
            return pf.fail("mode", "PROMOVENT_ENABLE_LIVE is not 'yes'")
        pf.passed("mode", mode.value)
        if mode.value == "autonomous_live":
            a = self.autonomy
            day = time.strftime("%Y-%m-%d", time.gmtime(self.now()))
            today = [o for o in self.store.orders(self.venue) if o["role"] == "entry" and o["ts"][:10] == day]
            if not a.active:
                return pf.fail("autonomy", "autonomous trading not activated (POST /api/live/autonomy)")
            if sig.symbol not in a.allowed_symbols:
                return pf.fail("autonomy", f"{sig.symbol} not in allowed_symbols {a.allowed_symbols}")
            if sig.strategy not in a.allowed_strategies:
                return pf.fail("autonomy", f"{sig.strategy} not in allowed_strategies")
            if len(today) >= a.max_orders_per_day:
                return pf.fail("autonomy", f"{len(today)} live entries today = max {a.max_orders_per_day}")
            pf.passed("autonomy")
        lock = self.risk.lockouts(self.state)
        if lock:
            return pf.fail("kill_switch", "; ".join(lock))
        pf.passed("kill_switch")
        if sig.strategy not in self.validated:
            return pf.fail("strategy", f"{sig.strategy} has not passed the validation gate")
        pf.passed("strategy")
        if sig.side != 1:
            return pf.fail("long_only", "spot execution is long-only; short signals need a margin/derivatives venue")
        pf.passed("long_only")
        if not sig.stop or sig.stop >= price:
            return pf.fail("stop_loss", f"stop {sig.stop} must be set and below price {price}")
        if not sig.target or sig.target <= price:
            return pf.fail("stop_loss", f"target {sig.target} must be above price {price}")
        pf.passed("stop_loss", f"stop {sig.stop}")
        age = self.now() - price_ts
        if age > self.max_age or age < -5:
            return pf.fail("market_data", f"price is {age:.0f}s old (max {self.max_age:.0f}s): stale or clock skew")
        pf.passed("market_data", f"{age:.0f}s old")
        try:
            perm = self.permissions()
        except ExecError as e:
            return pf.fail("connection", str(e))
        pf.passed("connection", self.venue + (" testnet" if self.client.testnet else " MAINNET"))
        if not perm.can_trade:
            return pf.fail("permissions", f"API key cannot trade spot: {perm.detail}")
        if perm.withdrawals_enabled:
            return pf.fail("permissions", "API key has WITHDRAWALS ENABLED; create a trade-only key")
        if perm.withdrawals_enabled is None and not self.client.testnet:
            return pf.fail("permissions", "could not confirm withdrawals are disabled for this key; refusing on mainnet")
        pf.passed("permissions", "trade on, withdrawals off" if perm.withdrawals_enabled is False
                  else "trade on (testnet: withdrawal flag not exposed)")

        # size against the cash actually available on the exchange
        try:
            bal = self.client.balances()
        except ExecError as e:
            return pf.fail("balance", str(e))
        quote = sig.symbol.split("/")[1]
        free_quote = bal.get(quote, (0.0, 0.0))[0]
        self.state.equity = max(self.state.equity, 0.0)
        sized = Signal(sig.strategy, sig.symbol, sig.side, price, sig.stop, sig.target, sig.bar_time, sig.reason)
        dec = self.risk.evaluate(sized, self.state, correlations)
        if not dec.approved:
            return pf.fail("risk", "; ".join(dec.reasons))
        pf.passed("risk", "; ".join(dec.reasons))
        try:
            rules = self.client.rules(sig.symbol)
        except ExecError as e:
            return pf.fail("exchange_rules", str(e))
        qty = rules.qty(dec.qty)
        if mode.value == "autonomous_live" and qty * price > self.autonomy.max_order_notional:
            qty = rules.qty(self.autonomy.max_order_notional / price)
        if qty < rules.min_qty or qty <= 0:
            return pf.fail("exchange_rules", f"size {qty} below exchange minimum {rules.min_qty}")
        if qty * price < rules.min_notional:
            return pf.fail("exchange_rules", f"notional {qty * price:.2f} below exchange minimum {rules.min_notional}")
        pf.passed("exchange_rules", f"qty {qty} (step {rules.step})")
        need = qty * price * (1 + self.fee_buffer)
        if free_quote < need:
            return pf.fail("balance", f"free {quote} {free_quote:.2f} < required {need:.2f}")
        pf.passed("balance", f"free {quote} {free_quote:.2f}")
        pf.qty, pf.risk_amount = qty, qty * abs(price - sig.stop)
        coid = self.coid(sig)
        if self.store.order_exists(coid):
            return pf.fail("duplicate", f"client order id {coid} already used")
        try:
            self.client.get(sig.symbol, coid)
            return pf.fail("duplicate", f"exchange already has order {coid}")
        except OrderNotFound:
            pf.passed("duplicate", coid)
        except ExecError as e:
            return pf.fail("duplicate", f"could not check exchange for {coid}: {e}")
        return pf

    @staticmethod
    def coid(sig: Signal) -> str:
        from ..paper import client_order_id
        return client_order_id(sig)

    # ------------------------------------------------------------------ mode 4
    def propose(self, sig: Signal, price: float, price_ts: float, actor: str) -> dict:
        if self.settings.mode.value != "assisted_live":
            raise LiveOrderRejected(None, "propose() is for assisted_live mode")
        pf = self.preflight(sig, price, price_ts)
        self.store.audit(actor, "live_preflight", {"coid": self.coid(sig), **pf.as_dict()})
        if not pf.ok:
            raise LiveOrderRejected(pf)
        token = secrets.token_urlsafe(16)
        self.pending[token] = Pending(token, sig, self.now() + self.ttl, pf, actor)
        return {"token": token, "expires_in_s": self.ttl, "preflight": pf.as_dict(), "symbol": sig.symbol,
                "qty": pf.qty, "price": price, "stop": sig.stop, "target": sig.target}

    def confirm(self, token: str, price: float, price_ts: float, actor: str) -> dict:
        p = self.pending.pop(token, None)
        if p is None:
            raise LiveOrderRejected(None, "unknown or already used confirmation token")
        if self.now() > p.expires:
            raise LiveOrderRejected(None, "confirmation expired; propose again")
        self.store.audit(actor, "live_confirmed", {"coid": self.coid(p.signal), "proposed_by": p.actor})
        return self._submit(p.signal, price, price_ts, actor)

    # ------------------------------------------------------------------ mode 5
    def execute(self, sig: Signal, price: float, price_ts: float, actor: str = "autonomous") -> dict:
        if self.settings.mode.value != "autonomous_live":
            raise LiveOrderRejected(None, "execute() is for autonomous_live mode; assisted mode needs propose/confirm")
        return self._submit(sig, price, price_ts, actor)

    # ------------------------------------------------------------------ submission
    def _submit(self, sig: Signal, price: float, price_ts: float, actor: str) -> dict:
        pf = self.preflight(sig, price, price_ts)
        coid = self.coid(sig)
        self.store.audit(actor, "live_preflight", {"coid": coid, **pf.as_dict()})
        if not pf.ok:
            raise LiveOrderRejected(pf)
        self.store.save_order(client_order_id=coid, venue=self.venue, testnet=self.client.testnet, role="entry",
                              symbol=sig.symbol, side=sig.side, order_type="market", qty=pf.qty, price=price,
                              stop=sig.stop, target=sig.target, strategy=sig.strategy, status="SUBMITTING",
                              decision=pf.as_dict())
        try:
            ack = self.client.place(sig.symbol, sig.side, "market", pf.qty, coid)
        except ExecError as e:
            self.store.update_order(coid, status="REJECTED", error=str(e))
            self.store.risk_event("order_rejected", "warn", {"coid": coid, "error": str(e)})
            raise LiveOrderRejected(None, f"exchange rejected entry: {e}") from e
        self.store.update_order(coid, exchange_order_id=ack.exchange_id, status=ack.status, filled_qty=ack.filled_qty,
                                avg_price=ack.avg_price)
        st = self._await_fill(sig.symbol, coid, ack)
        result = {"client_order_id": coid, "exchange": self.venue, "testnet": self.client.testnet,
                  "status": st.status, "filled_qty": st.filled_qty, "avg_price": st.avg_price, "protection": None}
        if st.filled_qty <= 0:
            self.store.audit(actor, "live_entry_unfilled", result)
            return result
        result["protection"] = self._protect(sig, coid, st, actor)
        self.store.audit(actor, "live_entry_filled", result)
        return result

    def _await_fill(self, symbol: str, coid: str, st: OrderState) -> OrderState:
        deadline = self.now() + self.fill_timeout
        while not st.final and self.now() < deadline:
            self.sleep(self.poll_s)
            try:
                st = self.client.get(symbol, coid)
            except ExecError as e:
                self.store.risk_event("order_status_unknown", "warn", {"coid": coid, "error": str(e)})
                continue
            self.store.update_order(coid, status=st.status, filled_qty=st.filled_qty, avg_price=st.avg_price)
        if not st.final:  # partial or resting: cancel the remainder, keep what filled
            try:
                st = self.client.cancel(symbol, coid)
            except ExecError as e:
                self.store.risk_event("cancel_failed", "critical", {"coid": coid, "error": str(e)})
            self.store.update_order(coid, status=st.status, filled_qty=st.filled_qty, avg_price=st.avg_price)
        return st

    def _protect(self, sig: Signal, coid: str, st: OrderState, actor: str) -> dict:
        rules = self.client.rules(sig.symbol)
        qty = rules.qty(st.filled_qty * (1 - 0.001))  # exchanges may take the fee in the base asset
        pcoid = coid[:26] + "p"
        try:
            legs = self.client.protect(sig.symbol, qty, sig.stop, sig.target, pcoid)
        except ExecError as e:
            # unprotected position: flatten it now
            self.store.risk_event("protection_failed", "critical", {"coid": coid, "error": str(e)})
            exit_id = coid[:26] + "x"
            try:
                self.client.place(sig.symbol, -1, "market", qty, exit_id)
                self.store.save_order(client_order_id=exit_id, venue=self.venue, testnet=self.client.testnet, role="exit",
                                      parent_id=coid, symbol=sig.symbol, side=-1, order_type="market", qty=qty,
                                      status="NEW", strategy=sig.strategy)
                closed = "position closed at market"
            except ExecError as e2:
                closed = f"EMERGENCY EXIT FAILED: {e2}; close manually on the exchange"
            self.state.kill_switch, self.state.kill_reason = True, f"protective order failed for {coid}"
            self.store.audit(actor, "kill_switch", {"reason": self.state.kill_reason})
            return {"ok": False, "error": str(e), "action": closed}
        for leg in legs:
            self.store.save_order(client_order_id=leg.client_id or pcoid, venue=self.venue, testnet=self.client.testnet,
                                  role="oco" if len(legs) > 1 or self.venue == "okx" else "stop", parent_id=coid,
                                  exchange_order_id=leg.exchange_id, symbol=sig.symbol, side=-1, order_type="protective",
                                  qty=qty, stop=sig.stop, target=sig.target, strategy=sig.strategy, status=leg.status)
        self.store.open_position(venue=self.venue, symbol=sig.symbol, side=1, qty=qty, entry=st.avg_price or 0.0,
                                 stop=sig.stop, target=sig.target, strategy=sig.strategy, entry_order_id=coid)
        tp_on_exchange = self.venue in ("binance", "okx")
        return {"ok": True, "legs": [leg.client_id for leg in legs], "qty": qty,
                "take_profit": "on exchange (OCO)" if tp_on_exchange else "watched by engine"}

    # ------------------------------------------------------------------ reconciliation
    def reconcile(self) -> dict:
        """Compare every non-final local order with the exchange and update it."""
        changed, missing, errors = [], [], []
        for o in self.store.orders(self.venue, status=["SUBMITTING", "NEW", "PARTIALLY_FILLED", "PENDING_TRIGGER"]):
            try:
                st = self.client.get(o["symbol"], o["client_order_id"])
            except OrderNotFound:
                if o["status"] == "SUBMITTING":
                    self.store.update_order(o["client_order_id"], status="REJECTED", error="never reached the exchange")
                missing.append(o["client_order_id"])
                continue
            except ExecError as e:
                errors.append(f"{o['client_order_id']}: {e}")
                continue
            if st.status != o["status"] or abs(st.filled_qty - (o["filled_qty"] or 0)) > 1e-12:
                self.store.update_order(o["client_order_id"], status=st.status, filled_qty=st.filled_qty, avg_price=st.avg_price)
                changed.append({"coid": o["client_order_id"], "from": o["status"], "to": st.status, "filled": st.filled_qty})
        report = {"venue": self.venue, "changed": changed, "missing_on_exchange": missing, "errors": errors}
        if changed or missing or errors:
            self.store.audit("reconciler", "reconcile", report)
        return report

    def watch_take_profit(self, symbol: str, price: float) -> list[dict]:
        """For venues without exchange-side OCO (Bybit): at target, cancel the stop then sell."""
        if self.venue != "bybit":
            return []
        out = []
        for p in self.store.positions(self.venue):
            if p["symbol"] != symbol or price < p["target"]:
                continue
            stop_id = p["entry_order_id"][:26] + "p"
            stop_id = stop_id[:30] + "sl"
            try:
                self.client.cancel(symbol, stop_id)
                ex = self.client.place(symbol, -1, "market", p["qty"], p["entry_order_id"][:26] + "t")
                out.append({"symbol": symbol, "action": "take_profit", "order": ex.client_id})
            except ExecError as e:
                self.store.risk_event("take_profit_failed", "critical", {"position": p["id"], "error": str(e)})
        return out


__all__ = ["LiveExecutionEngine", "Autonomy", "Preflight", "LiveOrderRejected", "InsufficientBalance"]
