"""Risk Guardian: independent service that watches the account and enforces the breach protocol.

Limits (RiskConfig): daily loss 2 % of start-of-day equity; total drawdown 2 % from the high-water mark
(or from initial equity with drawdown_basis='initial'); the kill switch.

On a breach, in this order:
 1. block new entries     - engages the kill switch (every order path checks it: paper agent, live engine, autopilot)
 2. cancel pending entries - live: every resting entry order on the exchange is cancelled
 3. reconcile             - live: local orders vs exchange
 4. emergency policy      - PROMOVENT_EMERGENCY_POLICY=protect (default): keep positions, verify each has a stop
                            (exchange-side order for live; paper positions always carry their stop); missing stop => close.
                            =close: close every position at market.
 5. notify                - risk_warning notification + critical risk event + audit entry
 6. authorization         - stays locked until an admin calls resume() with the confirmation phrase. If the breach
                            condition still holds, resume is refused unless the admin also resets the baseline
                            (accepting the loss as the new starting point), which is audited.
A stop-loss is not a guaranteed maximum loss: gaps and thin books can fill beyond it. The guardian checks
realized results after the fact; it does not assume the stop held.
"""
from __future__ import annotations

import os

from .execution.clients import ExecError

RESUME_PHRASE = "I AUTHORIZE RESUMING TRADING"


class RiskGuardian:
    def __init__(self, app):
        self.app = app

    def breaches(self) -> list[str]:
        st, eng = self.app.broker.state, self.app.risk
        out = []
        if eng.daily_loss(st) >= eng.cfg.daily_loss_limit:
            out.append(f"daily loss {eng.daily_loss(st):.2%} >= {eng.cfg.daily_loss_limit:.2%}")
        if eng.drawdown(st) >= eng.cfg.max_drawdown:
            out.append(f"total drawdown {eng.drawdown(st):.2%} >= {eng.cfg.max_drawdown:.2%} ({eng.cfg.drawdown_basis})")
        if eng.weekly_loss(st) >= eng.cfg.weekly_loss_limit:
            out.append(f"weekly loss {eng.weekly_loss(st):.2%} >= {eng.cfg.weekly_loss_limit:.2%}")
        return out

    def status(self) -> dict:
        lock = self.app.store.kv_get("guardian_lock")
        st, eng = self.app.broker.state, self.app.risk
        return {"locked": bool(lock), "lock": lock, "breaches_now": self.breaches(),
                "daily_loss": eng.daily_loss(st), "daily_limit": eng.cfg.daily_loss_limit,
                "drawdown": eng.drawdown(st), "drawdown_limit": eng.cfg.max_drawdown, "drawdown_basis": eng.cfg.drawdown_basis,
                "risk_per_trade": eng.cfg.risk_per_trade, "equity": st.equity,
                "risk_budget_per_trade": st.equity * eng.cfg.risk_per_trade,
                "emergency_policy": os.getenv("PROMOVENT_EMERGENCY_POLICY", "protect")}

    def check(self, prices: dict[str, float] | None = None) -> dict:
        prices = prices or {}
        self.app.broker.state.equity = self.app.broker.equity(prices)
        b = self.breaches()
        if not b or self.app.store.kv_get("guardian_lock"):
            return {"breach": bool(b), "acted": False}
        return self.trip("; ".join(b), prices)

    def trip(self, reason: str, prices: dict[str, float]) -> dict:
        steps = {}
        self.app.broker.set_kill(True, f"guardian: {reason}")                                       # 1
        steps["block_entries"] = "kill switch engaged"
        cancelled, errors = [], []
        if self.app.settings.mode.is_live:
            try:
                eng = self.app.live()
                for o in self.app.store.orders(eng.venue, status=["NEW", "PARTIALLY_FILLED", "SUBMITTING"]):
                    if o["role"] != "entry":
                        continue
                    try:
                        eng.client.cancel(o["symbol"], o["client_order_id"])                         # 2
                        cancelled.append(o["client_order_id"])
                    except ExecError as e:
                        errors.append(f"cancel {o['client_order_id']}: {e}")
                steps["reconcile"] = eng.reconcile()                                               # 3
            except ExecError as e:
                errors.append(f"live engine: {e}")
        steps["cancelled_entries"], steps["errors"] = cancelled, errors
        policy = os.getenv("PROMOVENT_EMERGENCY_POLICY", "protect")                                # 4
        closed = []
        for p in list(self.app.broker.state.positions):
            no_stop = not p.stop or (p.side == 1 and p.stop >= p.entry) or (p.side == -1 and p.stop <= p.entry)
            if policy == "close" or no_stop:
                px = prices.get(p.symbol, p.entry)
                closed.append(self.app.broker.close(p, px, "guardian_close")["client_order_id"])
        steps["policy"], steps["closed_positions"] = policy, closed
        lock = {"reason": reason, "steps": steps, "requires_authorization": True}
        self.app.store.kv_set("guardian_lock", lock)
        self.app.store.risk_event("guardian_lock", "critical", lock)                                # 5
        self.app.store.audit("risk_guardian", "guardian_lock", lock)
        try:
            from .db.models import User
            self.app.notifier.notify("risk_warning", {"kind": "guardian lock", "detail": reason + " - trading locked until authorized"},
                                     self.app.store.list(User, 100))
        except Exception as e:  # notification failure must not undo the lock
            steps["notify_error"] = str(e)
        return {"breach": True, "acted": True, **lock}

    def resume(self, actor: str, phrase: str, reset_baseline: bool = False) -> dict:               # 6
        if phrase != RESUME_PHRASE:
            raise PermissionError(f"confirmation phrase must be exactly: {RESUME_PHRASE}")
        still = self.breaches()
        st = self.app.broker.state
        if still and not reset_baseline:
            raise PermissionError("limits are still breached: " + "; ".join(still)
                                  + ". Resume only with reset_baseline=true (accepts current equity as the new baseline).")
        if reset_baseline:
            st.peak_equity = st.day_start_equity = st.week_start_equity = st.equity
            st.initial_equity = st.equity
        self.app.store.kv_set("guardian_lock", None)
        self.app.broker.set_kill(False, "")
        self.app.store.audit(actor, "guardian_resume", {"reset_baseline": reset_baseline, "equity": st.equity, "was": still})
        return {"locked": False, "reset_baseline": reset_baseline, "equity": st.equity}
