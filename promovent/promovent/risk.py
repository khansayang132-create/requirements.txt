"""Risk engine: the one component that can veto any trade.

`RiskEngine.evaluate()` returns a Decision. A trade goes ahead only if
approved; the execution layer refuses orders without an approved Decision.
Sizing: qty = equity x risk_per_trade / |entry - stop|, then capped so notional
<= equity x max_position_notional_pct (no leverage by default). Risk per trade
never rises after losses: the fraction is fixed by config, and the only
adjustment is downward (volatility scaling and drawdown throttling).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import RiskConfig
from .models import Position, Signal


@dataclass
class Decision:
    approved: bool
    qty: float = 0.0
    risk_amount: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def as_dict(self):
        return {"approved": self.approved, "qty": self.qty, "risk_amount": self.risk_amount, "reasons": self.reasons}


@dataclass
class RiskState:
    equity: float
    peak_equity: float
    day_start_equity: float
    week_start_equity: float
    positions: list[Position] = field(default_factory=list)
    kill_switch: bool = False
    kill_reason: str = ""
    initial_equity: float | None = None


class RiskEngine:
    def __init__(self, cfg: RiskConfig | None = None):
        self.cfg = cfg or RiskConfig()

    # --- portfolio measures -------------------------------------------------
    def heat(self, st: RiskState) -> float:
        return sum(p.open_risk for p in st.positions) / st.equity if st.equity > 0 else float("inf")

    def drawdown(self, st: RiskState) -> float:
        """Total drawdown vs the high-water mark, or vs initial equity when drawdown_basis='initial'."""
        base = st.initial_equity if self.cfg.drawdown_basis == "initial" and st.initial_equity else st.peak_equity
        return max(0.0, 1 - st.equity / base) if base and base > 0 else 0.0

    def daily_loss(self, st: RiskState) -> float:
        return max(0.0, 1 - st.equity / st.day_start_equity)

    def weekly_loss(self, st: RiskState) -> float:
        return max(0.0, 1 - st.equity / st.week_start_equity)

    def lockouts(self, st: RiskState) -> list[str]:
        r = []
        if st.kill_switch:
            r.append(f"kill switch engaged: {st.kill_reason or 'manual'}")
        if self.daily_loss(st) >= self.cfg.daily_loss_limit:
            r.append(f"daily loss {self.daily_loss(st):.2%} >= limit {self.cfg.daily_loss_limit:.2%}: locked until next UTC day")
        if self.weekly_loss(st) >= self.cfg.weekly_loss_limit:
            r.append(f"weekly loss {self.weekly_loss(st):.2%} >= limit {self.cfg.weekly_loss_limit:.2%}")
        if self.drawdown(st) >= self.cfg.max_drawdown:
            r.append(f"drawdown {self.drawdown(st):.2%} >= max {self.cfg.max_drawdown:.2%}")
        return r

    # --- the gate ------------------------------------------------------------
    def evaluate(self, sig: Signal, st: RiskState, correlations: dict[str, float] | None = None,
                 vol_scale: float = 1.0) -> Decision:
        cfg, reasons = self.cfg, []
        reasons += self.lockouts(st)
        if sig.side not in (1, -1):
            reasons.append("invalid side")
        risk_unit = sig.risk_per_unit
        if risk_unit <= 0 or (sig.side == 1 and sig.stop >= sig.entry) or (sig.side == -1 and sig.stop <= sig.entry):
            reasons.append("stop on the wrong side of entry or missing")
        if (sig.side == 1 and sig.target <= sig.entry) or (sig.side == -1 and sig.target >= sig.entry):
            reasons.append("target on the wrong side of entry")
        if sig.reward_risk < cfg.min_reward_risk:
            reasons.append(f"reward/risk {sig.reward_risk:.2f} < minimum {cfg.min_reward_risk}")
        if len(st.positions) >= cfg.max_concurrent_positions:
            reasons.append(f"{len(st.positions)} open positions = max {cfg.max_concurrent_positions}")
        if any(p.symbol == sig.symbol for p in st.positions):
            reasons.append(f"already positioned in {sig.symbol}")
        for p in st.positions:
            rho = (correlations or {}).get(p.symbol)
            if rho is not None and abs(rho) >= cfg.max_correlation and p.side * sig.side * (1 if rho > 0 else -1) > 0:
                reasons.append(f"correlation {rho:.2f} with open {p.symbol} adds same-direction exposure")
        if reasons:
            return Decision(False, reasons=reasons)

        # size: fixed fraction, only ever scaled down
        dd_throttle = 0.5 if self.drawdown(st) >= cfg.max_drawdown / 2 else 1.0
        frac = cfg.risk_per_trade * min(1.0, max(0.0, vol_scale)) * dd_throttle
        risk_amt = st.equity * frac
        heat_room = cfg.max_portfolio_heat * st.equity - sum(p.open_risk for p in st.positions)
        if heat_room <= 0:
            return Decision(False, reasons=[f"portfolio heat {self.heat(st):.2%} at max {cfg.max_portfolio_heat:.2%}"])
        risk_amt = min(risk_amt, heat_room)
        qty = risk_amt / risk_unit
        max_notional = st.equity * cfg.max_position_notional_pct * cfg.leverage
        notes = []
        if qty * sig.entry > max_notional:
            qty = max_notional / sig.entry
            notes.append("size capped by notional limit (no leverage)")
        if qty <= 0:
            return Decision(False, reasons=["computed size is zero"])
        if dd_throttle < 1:
            notes.append("size halved: drawdown past half of max")
        return Decision(True, qty=qty, risk_amount=qty * risk_unit, reasons=notes or ["approved"])


def vol_scale(atr_now: float, atr_median: float) -> float:
    """Volatility-adjusted sizing: shrink when ATR is above its median, never grow above 1."""
    if not atr_now or not atr_median or pd.isna(atr_now) or pd.isna(atr_median):
        return 1.0
    return min(1.0, atr_median / atr_now)
