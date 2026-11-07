"""Post-trade review: what happened, and was the trade's hypothesis right - separately from whether it made money."""
from __future__ import annotations

import pandas as pd


def evaluate(trade: dict, meta: dict, regime_exit: str | None, expected_slippage_bps: float) -> dict:
    """`trade` = closed-trade dict from the broker; `meta` = data recorded at entry (signal price, regime, score)."""
    side, entry, exit_ = trade["side"], trade["entry"], trade["exit"]
    risk_unit = abs(entry - trade["stop"]) or 1e-12
    r = (exit_ - entry) * side / risk_unit
    sig_px = meta.get("signal_price")
    slip = (entry - sig_px) / sig_px * 1e4 * side if sig_px else None
    hit_target = trade["reason"] == "target"
    hit_stop = trade["reason"] == "stop"
    profitable = trade["pnl"] > 0
    hypothesis = "correct" if hit_target else "wrong" if hit_stop else "undecided"
    notes = []
    if profitable and not hit_target:
        notes.append("profitable without reaching the target: outcome was not the predicted move")
    if not profitable and hit_target:
        notes.append("target reached but costs turned the trade negative: edge smaller than costs")
    if regime_exit and meta.get("regime") and regime_exit != meta["regime"]:
        notes.append(f"regime changed during the trade ({meta['regime']} -> {regime_exit})")
    exec_ok = slip is None or slip <= 2 * expected_slippage_bps
    if not exec_ok:
        notes.append(f"entry slippage {slip:.1f} bps above twice the {expected_slippage_bps:.1f} bps budget")
    return {"r_multiple": r, "slippage_bps": slip, "hypothesis": hypothesis, "profitable": profitable,
            "lucky": profitable and hypothesis != "correct", "regime_changed": bool(regime_exit and meta.get("regime")
                                                                                    and regime_exit != meta["regime"]),
            "execution_ok": exec_ok, "notes": notes}


def holding_hours(opened, closed) -> float:
    try:
        return (pd.Timestamp(closed) - pd.Timestamp(opened)).total_seconds() / 3600
    except (TypeError, ValueError):
        return 0.0
