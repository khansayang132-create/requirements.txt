"""Paper trading broker and the execution gate.

ExecutionAgent is the only path to an order. It checks, in order:
mode allows orders -> strategy passed validation (paper/live) -> risk Decision
approved -> client_order_id not seen before (no duplicates). Live modes are
refused: this build has no signed exchange client (see STATUS.md). There is no
withdrawal function anywhere in the codebase, by design.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pandas as pd

from .backtest import Costs
from .config import Mode, Settings
from .models import Position, Signal
from .risk import Decision, RiskEngine, RiskState
from .db import Store


class OrderRejected(RuntimeError):
    pass


class LiveTradingUnavailable(OrderRejected):
    pass


def client_order_id(sig: Signal) -> str:
    raw = f"{sig.strategy}|{sig.symbol}|{sig.side}|{sig.bar_time}"
    # letters and digits only: valid as Binance newClientOrderId, Bybit orderLinkId and OKX clOrdId
    return "pv" + hashlib.sha256(raw.encode()).hexdigest()[:24]


@dataclass
class Fill:
    client_order_id: str
    qty: float
    price: float
    complete: bool


class PaperBroker:
    """Simulated broker. State is persisted (kv `paper_account` + open `positions` rows) and reloaded on
    start, so a restart or crash never forgets cash, positions, loss baselines or the kill switch."""

    def __init__(self, store: Store, initial: float = 10_000.0, costs: Costs | None = None, persist: bool = True):
        self.store, self.costs, self.persist = store, costs or Costs(), persist
        self.cash, self.realized = initial, 0.0
        self.state = RiskState(initial, initial, initial, initial, initial_equity=initial)
        self.day = self.week = None
        if persist:
            self._load(initial)

    def _load(self, initial: float) -> None:
        if not self.store.kv_get("paper_account"):
            self.save()
            return
        self.reload()

    def reload(self) -> None:
        """Re-read the account from the database. Called before every change, because the API and the worker are
        separate processes, each with its own broker object; the database is the only source of truth."""
        if not self.persist:
            return
        acct = self.store.kv_get("paper_account")
        if not acct:
            return
        self.cash, self.realized = acct["cash"], acct["realized"]
        self.state.peak_equity = acct["peak_equity"]
        self.state.day_start_equity, self.state.week_start_equity = acct["day_start_equity"], acct["week_start_equity"]
        self.day, self.week = acct.get("day"), acct.get("week")
        self.state.initial_equity = acct.get("initial_equity", self.state.initial_equity)
        kill = self.store.kv_get("kill_switch")
        if kill is None:  # databases written before the kill switch had its own record
            kill = {"on": acct.get("kill_switch", False), "reason": acct.get("kill_reason", "")}
        self.state.kill_switch, self.state.kill_reason = bool(kill["on"]), kill.get("reason", "")
        self.state.positions = []
        for row in self.store.positions("paper"):
            pos = Position(row["symbol"], row["side"], row["qty"], row["entry"], row["stop"], row["target"], row["strategy"],
                           pd.Timestamp(row["opened_at"]))
            pos._coid, pos._fees = row["entry_order_id"], row["fees"]  # type: ignore[attr-defined]
            self.state.positions.append(pos)
        self.state.equity = self.equity()

    def save(self) -> None:
        """Account fields only. The kill switch is written exclusively by set_kill(), so a process holding a stale
        copy can never re-engage or release it."""
        if not self.persist:
            return
        self.store.kv_set("paper_account", {
            "cash": self.cash, "realized": self.realized, "peak_equity": self.state.peak_equity,
            "day_start_equity": self.state.day_start_equity, "week_start_equity": self.state.week_start_equity,
            "day": self.day, "week": self.week, "initial_equity": self.state.initial_equity})

    def roll(self, now, prices: dict[str, float] | None = None) -> None:
        """Reset daily / weekly loss baselines at the UTC day / ISO-week boundary."""
        self.reload()
        eq = self.equity(prices)
        d, w = str(now.date()), "%d-W%02d" % now.isocalendar()[:2]
        if d != self.day:
            self.day, self.state.day_start_equity = d, eq
        if w != self.week:
            self.week, self.state.week_start_equity = w, eq
        self.state.equity = eq
        self.state.peak_equity = max(self.state.peak_equity, eq)
        self.save()

    def set_kill(self, on: bool, reason: str = "") -> None:
        self.state.kill_switch, self.state.kill_reason = on, reason
        if self.persist:
            self.store.kv_set("kill_switch", {"on": on, "reason": reason})

    def equity(self, prices: dict[str, float] | None = None) -> float:
        prices = prices or {}
        return self.cash + sum(p.unrealized(prices.get(p.symbol, p.entry)) for p in self.state.positions)

    def submit(self, sig: Signal, dec: Decision, coid: str, market_price: float, fill_ratio: float = 1.0,
               meta: dict | None = None) -> Fill:
        px = self.costs.adverse(market_price, sig.side)
        qty = dec.qty * fill_ratio
        fee = px * qty * self.costs.fee_bps / 1e4
        self.cash -= fee
        pos = Position(sig.symbol, sig.side, qty, px, sig.stop, sig.target, sig.strategy, pd.Timestamp.now(tz="UTC"))
        pos._coid, pos._fees = coid, fee  # type: ignore[attr-defined]
        self.state.positions.append(pos)
        self.store.save_order(client_order_id=coid, venue="paper", symbol=sig.symbol, side=sig.side, order_type="market",
                              qty=dec.qty, price=px, stop=sig.stop, target=sig.target, strategy=sig.strategy,
                              status="filled" if fill_ratio >= 1 else "partially_filled", filled_qty=qty, avg_price=px,
                              decision=json.loads(json.dumps({**dec.as_dict(), "meta": meta or {}, "signal_price": sig.entry},
                                                             default=str)))
        self.store.open_position(venue="paper", symbol=sig.symbol, side=sig.side, qty=qty, entry=px, stop=sig.stop,
                                 target=sig.target, strategy=sig.strategy, entry_order_id=coid, fees=fee)
        self.save()
        return Fill(coid, qty, px, fill_ratio >= 1)

    def on_price(self, symbol: str, price: float) -> list[dict]:
        """Mark-to-market; close positions whose stop or target is crossed."""
        self.reload()
        closed = []
        for p in list(self.state.positions):
            if p.symbol != symbol:
                continue
            hit = None
            if p.side == 1:
                hit = "stop" if price <= p.stop else "target" if price >= p.target else None
            else:
                hit = "stop" if price >= p.stop else "target" if price <= p.target else None
            if hit:
                closed.append(self.close(p, price, hit))
        eq = self.equity({symbol: price})
        self.state.equity = eq
        self.state.peak_equity = max(self.state.peak_equity, eq)
        if closed:
            self.save()
        return closed

    def close(self, p: Position, price: float, reason: str) -> dict:
        px = self.costs.adverse(price, -p.side) if reason != "target" else price
        fee = px * p.qty * self.costs.fee_bps / 1e4
        gross = (px - p.entry) * p.qty * p.side
        self.cash += gross - fee
        pnl = gross - fee - p._fees  # type: ignore[attr-defined]
        self.realized += pnl
        self.state.positions.remove(p)
        self.store.close_position(p._coid, px, reason, pnl, fee + p._fees)  # type: ignore[attr-defined]
        self.save()
        return {"symbol": p.symbol, "reason": reason, "exit": px, "pnl": pnl, "client_order_id": p._coid,  # type: ignore[attr-defined]
                "gross": gross, "fees": fee + p._fees, "entry": p.entry, "qty": p.qty, "side": p.side,  # type: ignore[attr-defined]
                "stop": p.stop, "target": p.target, "strategy": p.strategy, "opened_at": p.opened_at}

    def snapshot(self, prices: dict[str, float] | None = None) -> dict:
        prices = prices or {}
        eng = RiskEngine()
        pos = [{"symbol": p.symbol, "side": p.side, "qty": p.qty, "entry": p.entry, "stop": p.stop, "target": p.target,
                "strategy": p.strategy, "unrealized": p.unrealized(prices.get(p.symbol, p.entry)),
                "open_risk": p.open_risk} for p in self.state.positions]
        return {"equity": self.equity(prices), "cash": self.cash, "realized_pnl": self.realized, "positions": pos,
                "heat": eng.heat(self.state), "drawdown": eng.drawdown(self.state),
                "kill_switch": self.state.kill_switch}


class ExecutionAgent:
    def __init__(self, settings: Settings, risk: RiskEngine, broker: PaperBroker, store: Store,
                 validated_strategies: set[str] | None = None):
        self.settings, self.risk, self.broker, self.store = settings, risk, broker, store
        self.validated = validated_strategies if validated_strategies is not None else set()
        self.pending_confirmations: dict[str, tuple[Signal, Decision]] = {}

    def kill(self, actor: str, reason: str) -> None:
        self.broker.set_kill(True, reason)
        self.store.audit(actor, "kill_switch", {"reason": reason})

    def execute(self, sig: Signal, market_price: float, actor: str = "system",
                correlations: dict[str, float] | None = None, fill_ratio: float = 1.0, meta: dict | None = None,
                rules=None) -> dict:
        mode = self.settings.mode
        coid = client_order_id(sig)
        if not mode.may_place_orders:
            raise OrderRejected(f"mode {mode.value} does not place orders")
        if mode.is_live:
            self.store.audit(actor, "live_order_refused", {"coid": coid, "reason": "paper agent in live mode"})
            raise LiveTradingUnavailable("live modes use LiveExecutionEngine (promovent.execution), not the paper agent")
        if sig.strategy not in self.validated:
            raise OrderRejected(f"strategy {sig.strategy} has not passed the validation gate")
        if self.store.order_exists(coid):
            raise OrderRejected(f"duplicate order {coid}")
        self.broker.reload()
        self.broker.state.equity = self.broker.equity({sig.symbol: market_price})
        dec = self.risk.evaluate(sig, self.broker.state, correlations)
        self.store.audit(actor, "risk_decision", {"coid": coid, **dec.as_dict()})
        if not dec.approved:
            raise OrderRejected("; ".join(dec.reasons))
        if rules is not None:  # exchange filters: round DOWN to the lot step; never enlarge to reach a minimum
            q = rules.qty(dec.qty)
            if q <= 0 or q < rules.min_qty or q * market_price < rules.min_notional:
                self.store.audit(actor, "filter_reject", {"coid": coid, "qty": dec.qty, "rounded": q, "min_qty": rules.min_qty,
                                                          "min_notional": rules.min_notional, "notional": q * market_price})
                raise OrderRejected(f"exchange filters: {q} x {market_price:.6g} = {q * market_price:.2f} below min notional "
                                    f"{rules.min_notional} or min qty {rules.min_qty}; position not enlarged to fit the minimum")
            dec.qty, dec.risk_amount = q, q * abs(sig.entry - sig.stop)
        fill = self.broker.submit(sig, dec, coid, market_price, fill_ratio, meta)
        self.store.audit(actor, "paper_fill", fill.__dict__)
        return {"client_order_id": coid, "qty": fill.qty, "price": fill.price, "complete": fill.complete,
                "decision": dec.as_dict(), "mode": Mode.PAPER.value}
