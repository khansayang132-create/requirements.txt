"""Autopilot: one `step()` per minute from the worker.

Order of every step (each stage writes what it decided):
 1. health gates  - market data fresh, exchange reachable, risk limits OK, kill switch off, live state
                    reconciled. Any failure => NO NEW ENTRIES this step (positions are still managed).
 2. manage        - mark open paper positions to the latest price; stops/targets close them; every
                    closed trade gets a TradeReview.
 3. roll          - daily / weekly loss baselines at UTC boundaries (persisted).
 4. search        - for every APPROVED combo (strategy, symbol, timeframe whose latest live-data research
                    passed the validation gate within `approval_days`), on each newly closed bar:
                    signal -> costed Candidate -> decision. Nothing approved => nothing traded.
 5. execute       - paper: ExecutionAgent; assisted_live: record + notify (the user confirms on /trading);
                    autonomous_live: LiveExecutionEngine.execute (its own 13 preflight checks apply).
Cursors (last processed bar per combo) are persisted, so a restart never re-trades or skips a bar.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta, timezone

import pandas as pd
from sqlalchemy import func, select

from ..backtest import Costs
from ..db.models import Opportunity, StrategyResearch, TradeReview, User, utcnow
from ..execution.clients import ExecError
from ..paper import OrderRejected
from ..scoring import score as score_fn
from ..service import DataUnavailable
from ..strategies import get_strategy
from ..ta.regime import classify
from . import opportunity, review

log = logging.getLogger("promovent.autopilot")


@dataclass
class Gate:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class StepResult:
    gates: list[Gate] = field(default_factory=list)
    entries_allowed: bool = False
    closed: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    decision: str = "wait"

    def as_dict(self):
        return {"gates": [g.__dict__ for g in self.gates], "entries_allowed": self.entries_allowed, "closed": self.closed,
                "candidates": self.candidates, "decision": self.decision}


class Autopilot:
    def __init__(self, app, costs: Costs | None = None, approval_days: float = 7, max_price_age_s: float = 150,
                 min_score: float = 0.0, now=lambda: pd.Timestamp.now(tz="UTC")):
        self.app, self.costs = app, costs or Costs()
        self.approval_days, self.max_price_age_s, self.min_score, self.now = approval_days, max_price_age_s, min_score, now
        from ..guardian import RiskGuardian
        self.guardian = RiskGuardian(app)
        self._rules: dict[str, object] = {}

    def rules(self, symbol: str):
        """Exchange filters for the data exchange (Binance exchangeInfo / OKX instruments), cached per symbol."""
        if symbol not in self._rules:
            from ..execution.clients import Rules
            ex = self.app.market.exchange
            if ex == "binance":
                from ..data.exchanges import Binance
                f = Binance().filters(symbol)
                self._rules[symbol] = Rules(f["step"], f["tick"], f["min_qty"], f["min_notional"])
            elif ex == "okx":
                import httpx
                d = httpx.get("https://www.okx.com/api/v5/public/instruments", params={"instType": "SPOT",
                              "instId": symbol.replace("/", "-")}, timeout=10).json()["data"][0]
                self._rules[symbol] = Rules(float(d["lotSz"]), float(d["tickSz"]), float(d["minSz"]), 0.0)
            else:
                return None
        return self._rules[symbol]

    # ---------------------------------------------------------------- approvals
    def approved(self) -> list[dict]:
        """Latest research row per combo; approved only if it passed on LIVE data recently."""
        since = utcnow() - timedelta(days=self.approval_days)
        with self.app.store.session() as s:
            latest = (select(StrategyResearch.strategy, StrategyResearch.symbol, StrategyResearch.timeframe,
                             func.max(StrategyResearch.id).label("id")).group_by(
                StrategyResearch.strategy, StrategyResearch.symbol, StrategyResearch.timeframe).subquery())
            rows = s.scalars(select(StrategyResearch).join(latest, StrategyResearch.id == latest.c.id)).all()
            def aware(t):
                return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
            return [{"strategy": r.strategy, "symbol": r.symbol, "timeframe": r.timeframe, "params": r.params}
                    for r in rows if r.passed and r.source == "live" and aware(r.ts) >= since]

    # ---------------------------------------------------------------- gates
    def gates(self, symbols: list[str]) -> tuple[list[Gate], dict[str, tuple[float, float]]]:
        g, prices = [], {}
        mode = self.app.settings.mode
        g.append(Gate("mode", mode.may_place_orders, mode.value))
        if self.app.broker.state.kill_switch:
            g.append(Gate("kill_switch", False, self.app.broker.state.kill_reason or "engaged"))
        lock = self.app.risk.lockouts(self.app.broker.state)
        g.append(Gate("risk_limits", not lock, "; ".join(lock) or "within limits"))
        glock = self.app.store.kv_get("guardian_lock")
        if glock:
            g.append(Gate("risk_guardian", False, "locked until authorized: " + glock.get("reason", "")))
        halted = self.app.store.kv_get("autopilot_halt")
        if halted:
            g.append(Gate("execution_consistency", False, halted.get("reason", "halted")))
        errs, stale = [], []
        now = time.time()
        stream = self.app.coord.get("stream_snapshot") or {}
        for s in symbols:
            snap = (stream.get("symbols") or {}).get(s)
            if snap and snap.get("price") and snap.get("timestamp_ms"):
                prices[s] = (snap["price"], snap["timestamp_ms"] / 1000)
            else:
                try:
                    df, meta = self.app.market.ohlcv(s, "1m", 60)
                    prices[s] = (float(df["close"].iloc[-1]), meta.timestamp_ms / 1000)
                except DataUnavailable as e:
                    errs.append(f"{s}: {e}")
                    continue
            age = now - prices[s][1]
            if age > self.max_price_age_s:
                stale.append(f"{s} {age:.0f}s")
        g.append(Gate("exchange_connectivity", not errs, "; ".join(errs)[:300] or self.app.market.exchange + " reachable"))
        g.append(Gate("market_data_fresh", not stale and not errs,
                      ("stale: " + ", ".join(stale)) if stale else f"all prices <= {self.max_price_age_s:.0f}s old"))
        return g, prices

    # ---------------------------------------------------------------- step
    def step(self) -> StepResult:
        res = StepResult()
        approved = self.approved()
        symbols = sorted({p.symbol for p in self.app.broker.state.positions} | {a["symbol"] for a in approved}) or ["BTC/USDT"]
        res.gates, prices = self.gates(symbols)
        res.entries_allowed = all(x.ok for x in res.gates)
        # manage open positions even when entries are blocked
        for p in list(self.app.broker.state.positions):
            if p.symbol in prices:
                for t in self.app.broker.on_price(p.symbol, prices[p.symbol][0]):
                    res.closed.append(self._review(t))
        self.app.broker.roll(self.now(), {s: v[0] for s, v in prices.items()})
        g = self.guardian.check({s: v[0] for s, v in prices.items()})
        if g.get("acted"):
            res.gates.append(Gate("risk_guardian", False, "locked: " + g["reason"]))
            res.entries_allowed = False
        if not approved:
            res.decision = "wait: no strategy has passed live-data validation"
        elif not res.entries_allowed:
            res.decision = "wait: " + "; ".join(f"{x.name}: {x.detail}" for x in res.gates if not x.ok)
        else:
            res.decision = "searching"
            for a in approved:
                c = self._process(a, prices)
                if c:
                    res.candidates.append(c)
            if not any(c.get("decision") == "taken" for c in res.candidates):
                res.decision = "wait: no actionable opportunity"
            else:
                res.decision = "traded"
        state = {"ts": str(self.now()), **res.as_dict(), "approved": approved}
        self.app.store.kv_set("autopilot_last_step", state)
        self.app.coord.set("autopilot_last_step", state, 600)
        return res

    def _process(self, a: dict, prices: dict) -> dict | None:
        strat, sym, tf = a["strategy"], a["symbol"], a["timeframe"]
        key = f"cursor:{strat}:{sym}:{tf}"
        try:
            df, meta = self.app.market.ohlcv(sym, tf, 400)
        except DataUnavailable:
            return None
        bar = str(df.index[-1])
        if self.app.store.kv_get(key) == bar:
            return None  # this closed bar was already evaluated
        st = get_strategy(strat, a.get("params") or {})
        sig = st.signals(df).iloc[-1]
        self.app.store.kv_set(key, bar)
        if not sig["side"]:
            return None
        reg = classify(df).iloc[-1]
        sc = score_fn(df, reward_risk=None)
        cand = opportunity.build(strat, sym, tf, df, sig, reg, sc, self.costs, self.app.risk, self.app.broker.state, self.min_score)
        decision, coid = "rejected", None
        if cand.actionable and self.now() < cand.expires_at:
            decision, coid = self._execute(cand, prices.get(sym))
        elif cand.actionable:
            decision, cand.reason = "expired", "signal expired before execution"
        self.app.store.add(Opportunity(strategy=strat, exchange=meta.exchange, symbol=sym, timeframe=tf,
                                       bar_time=cand.bar_time.to_pydatetime(), side=cand.side, entry=cand.entry, stop=cand.stop,
                                       target=cand.target, qty=cand.qty, reward_risk=cand.reward_risk,
                                       net_reward_risk=cand.net_reward_risk, expected_cost_bps=cand.expected_cost_bps,
                                       regime=cand.regime, score=cand.score, supporting=cand.supporting,
                                       conflicting=cand.conflicting, expires_at=cand.expires_at.to_pydatetime(),
                                       decision=decision, reason=cand.reason, client_order_id=coid,
                                       venue="paper" if self.app.settings.mode.value == "paper" else self.app.settings.mode.value))
        return {**cand.as_dict(), "decision": decision}

    def _execute(self, cand, px) -> tuple[str, str | None]:
        mode = self.app.settings.mode.value
        sig = cand.signal()
        price, ts = (px if px else (cand.entry, time.time()))
        meta = {"timeframe": cand.timeframe, "regime": cand.regime, "score": cand.score}
        if mode == "paper":
            self.app.agent.validated.add(cand.strategy)  # approved for this combo by live-data research
            try:
                rules = self.rules(cand.symbol)
            except Exception as e:  # filters unknown => cannot prove the order is valid => do not trade
                cand.reason = f"exchange filters unavailable: {e}"
                return "rejected", None
            try:
                r = self.app.agent.execute(sig, price, actor="autopilot", meta=meta, rules=rules)
                return "taken", r["client_order_id"]
            except OrderRejected as e:
                cand.reason = f"execution: {e}"
                return "rejected", None
        if mode == "assisted_live":
            self.app.notifier.notify("signal", {"symbol": cand.symbol, "side": "long" if cand.side > 0 else "short",
                                                "strategy": cand.strategy, "entry": cand.entry, "stop": cand.stop,
                                                "target": cand.target, "score": cand.score, "source": "live", "ts": str(cand.bar_time)},
                                     self.app.store.list(User, 100))
            cand.reason = "awaiting user confirmation on /trading"
            return "proposed", None
        if mode == "autonomous_live":
            try:
                r = self.app.live().execute(sig, price, ts, actor="autopilot")
                return "taken", r["client_order_id"]
            except (ExecError, Exception) as e:  # LiveOrderRejected or exchange errors: record, never retry blindly
                cand.reason = f"live: {e}"
                return "rejected", None
        return "rejected", None

    def _review(self, t: dict) -> dict:
        order = self.app.store.get_order(t["client_order_id"]) or {}
        meta = (order.get("decision") or {}).get("meta", {})
        meta["signal_price"] = (order.get("decision") or {}).get("signal_price")
        reg_exit = None
        tf = meta.get("timeframe")
        if tf:
            try:
                reg_exit = str(classify(self.app.market.ohlcv(t["symbol"], tf, 400)[0])["regime"].iloc[-1])
            except DataUnavailable:
                pass
        ev = review.evaluate(t, meta, reg_exit, self.costs.slippage_bps)
        closed_at = self.now()
        self.app.store.add(TradeReview(venue="paper", client_order_id=t["client_order_id"], strategy=t["strategy"], symbol=t["symbol"],
                                       timeframe=tf, side=t["side"], qty=t["qty"], signal_price=meta.get("signal_price"),
                                       entry=t["entry"], exit=t["exit"], stop=t["stop"], target=t["target"], exit_reason=t["reason"],
                                       fees=t["fees"], funding=0.0, slippage_bps=ev["slippage_bps"], gross_pnl=t["gross"],
                                       net_pnl=t["pnl"], r_multiple=ev["r_multiple"],
                                       holding_hours=review.holding_hours(t["opened_at"], closed_at),
                                       signal_score=meta.get("score"), regime_entry=meta.get("regime"), regime_exit=reg_exit,
                                       evaluation=ev))
        return {"client_order_id": t["client_order_id"], "pnl": t["pnl"], **ev}

    # ---------------------------------------------------------------- execution consistency (live)
    def check_consistency(self) -> dict:
        if not self.app.settings.mode.is_live:
            return {"ok": True, "detail": "paper mode"}
        try:
            rep = self.app.live().reconcile()
        except ExecError as e:
            rep = {"errors": [str(e)], "missing_on_exchange": [], "changed": []}
        bad = rep.get("errors") or rep.get("missing_on_exchange")
        if bad:
            self.app.store.kv_set("autopilot_halt", {"reason": f"reconciliation mismatch: {bad}"[:400], "ts": str(self.now())})
            self.app.store.risk_event("execution_halted", "critical", rep)
            return {"ok": False, "detail": rep}
        if self.app.store.kv_get("autopilot_halt"):
            self.app.store.kv_set("autopilot_halt", None)
        return {"ok": True, "detail": rep}
