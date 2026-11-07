"""Opportunity engine: turns a strategy signal into a fully costed, sized, expiring trade candidate.

Expected round-trip cost (bps) = 2 x taker fee + spread + 2 x slippage. Costs are charged against both
legs of the trade: net R:R = (reward - cost) / (risk + cost). A candidate is only actionable when the
net R:R still clears the risk engine's minimum; otherwise the costs eat the edge and the answer is WAIT.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from ..backtest import Costs
from ..models import TF_SECONDS, Signal
from ..risk import RiskEngine, RiskState


@dataclass
class Candidate:
    strategy: str
    symbol: str
    timeframe: str
    bar_time: pd.Timestamp
    side: int
    entry: float
    stop: float
    target: float
    reward_risk: float
    net_reward_risk: float
    expected_cost_bps: float
    expires_at: pd.Timestamp
    regime: str
    score: float
    qty: float = 0.0
    supporting: list = field(default_factory=list)
    conflicting: list = field(default_factory=list)
    actionable: bool = False
    reason: str = ""

    def signal(self) -> Signal:
        return Signal(self.strategy, self.symbol, self.side, self.entry, self.stop, self.target, self.bar_time, self.reason)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["bar_time"], d["expires_at"] = str(self.bar_time), str(self.expires_at)
        return d


def expected_cost_bps(c: Costs) -> float:
    return 2 * c.fee_bps + c.spread_bps + 2 * c.slippage_bps


def build(strategy: str, symbol: str, tf: str, df: pd.DataFrame, sig_row: pd.Series, regime_row: pd.Series, score: dict,
          costs: Costs, risk: RiskEngine, state: RiskState, min_score: float = 0.0) -> Candidate:
    bar = df.index[-1]
    entry = float(df["close"].iloc[-1])
    side, stop, target = int(sig_row["side"]), float(sig_row["stop"]), float(sig_row["target"])
    r = abs(entry - stop)
    reward = abs(target - entry)
    cost = entry * expected_cost_bps(costs) / 1e4
    rr = reward / r if r > 0 else 0.0
    net = (reward - cost) / (r + cost) if r > 0 else 0.0
    expires = bar + pd.Timedelta(seconds=2 * TF_SECONDS[tf])  # bar open + 1 bar = its close; valid for one more bar
    cand = Candidate(strategy, symbol, tf, bar, side, entry, stop, target, rr, net, expected_cost_bps(costs), expires,
                     str(regime_row["regime"]), float(score.get("score", 0.0)))
    d = score.get("direction", 0)
    cand.supporting = [f"score {cand.score:.1f} ({score.get('grade')})"] + ([f"trend bias agrees ({'up' if d == 1 else 'down'})"]
                                                                          if d == side else [])
    if d and d != side:
        cand.conflicting.append("scoring trend bias disagrees with the signal")
    if not regime_row["tradeable"]:
        cand.conflicting.append(f"regime {cand.regime}: not tradeable")
    for u in score.get("unavailable", []):
        cand.conflicting.append(f"no data: {u}")
    if not regime_row["tradeable"]:
        cand.reason = f"regime {cand.regime} is not tradeable"
        return cand
    if net < risk.cfg.min_reward_risk:
        cand.reason = f"net R:R {net:.2f} after {cand.expected_cost_bps:.0f} bps costs < {risk.cfg.min_reward_risk}"
        return cand
    if cand.score < min_score:
        cand.reason = f"score {cand.score:.1f} < minimum {min_score}"
        return cand
    dec = risk.evaluate(cand.signal(), state)
    if not dec.approved:
        cand.reason = "risk: " + "; ".join(dec.reasons)
        return cand
    cand.qty, cand.actionable, cand.reason = dec.qty, True, "all checks passed"
    return cand
