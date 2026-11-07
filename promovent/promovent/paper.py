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
    def __init__(self, store: Store, initial: float = 10_000.0, costs: Costs | None = None):
        self.store, self.costs = store, costs or Costs()
        self.cash = initial
        self.state = RiskState(initial, initial, initial, initial)
        self.realized = 0.0

    def equity(self, prices: dict[str, float] | None = None) -> float:
        prices = prices or {}
        return self.cash + sum(p.unrealized(prices.get(p.symbol, p.entry)) for p in self.state.positions)

    def submit(self, sig: Signal, dec: Decision, coid: str, market_price: float, fill_ratio: float = 1.0) -> Fill:
        px = self.costs.adverse(market_price, sig.side)
        qty = dec.qty * fill_ratio
        fee = px * qty * self.costs.fee_bps / 1e4
        self.cash -= fee
        pos = Position(sig.symbol, sig.side, qty, px, sig.stop, sig.target, sig.strategy)
        pos._coid, pos._fees = coid, fee  # type: ignore[attr-defined]
        self.state.positions.append(pos)
        self.store.save_order(client_order_id=coid, venue="paper", symbol=sig.symbol, side=sig.side, order_type="market",
                              qty=dec.qty, price=px, stop=sig.stop, target=sig.target, strategy=sig.strategy,
                              status="filled" if fill_ratio >= 1 else "partially_filled", filled_qty=qty, avg_price=px,
                              decision=json.loads(json.dumps(dec.as_dict())))
        self.store.open_position(venue="paper", symbol=sig.symbol, side=sig.side, qty=qty, entry=px, stop=sig.stop,
                                 target=sig.target, strategy=sig.strategy, entry_order_id=coid, fees=fee)
        return Fill(coid, qty, px, fill_ratio >= 1)

    def on_price(self, symbol: str, price: float) -> list[dict]:
        """Mark-to-market; close positions whose stop or target is crossed."""
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
        return {"symbol": p.symbol, "reason": reason, "exit": px, "pnl": pnl}

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
        self.broker.state.kill_switch, self.broker.state.kill_reason = True, reason
        self.store.audit(actor, "kill_switch", {"reason": reason})

    def execute(self, sig: Signal, market_price: float, actor: str = "system",
                correlations: dict[str, float] | None = None, fill_ratio: float = 1.0) -> dict:
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
        self.broker.state.equity = self.broker.equity({sig.symbol: market_price})
        dec = self.risk.evaluate(sig, self.broker.state, correlations)
        self.store.audit(actor, "risk_decision", {"coid": coid, **dec.as_dict()})
        if not dec.approved:
            raise OrderRejected("; ".join(dec.reasons))
        fill = self.broker.submit(sig, dec, coid, market_price, fill_ratio)
        self.store.audit(actor, "paper_fill", fill.__dict__)
        return {"client_order_id": coid, "qty": fill.qty, "price": fill.price, "complete": fill.complete,
                "decision": dec.as_dict(), "mode": Mode.PAPER.value}
