"""Strategy researcher: backtest + walk-forward + Monte Carlo + gate for every strategy x symbol x timeframe,
on LIVE exchange history, stored in `strategy_research`. Only these rows can approve a combo for trading."""
from __future__ import annotations

import logging

import numpy as np

from ..backtest import Costs, ValidationGate, monte_carlo, run, walk_forward
from ..config import research_risk
from ..db.models import StrategyResearch
from ..models import TF_SECONDS
from ..service import DataUnavailable
from ..strategies import REGISTRY, get_strategy

log = logging.getLogger("promovent.research")


def _grid(base: dict) -> list[dict]:
    g = [base]
    for k, v in base.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        for f in (0.8, 1.25):
            g.append({**base, k: int(round(v * f)) if isinstance(v, int) else v * f})
    return g[:9]


def research_combo(df, strategy: str, symbol: str, tf: str, costs: Costs, gate: ValidationGate) -> dict:
    st = get_strategy(strategy)
    res = run(df, st, symbol, 10_000, costs, risk=research_risk(), tf=tf)
    wf = walk_forward(df, lambda p: get_strategy(strategy, p), _grid(st.params), n_folds=3, costs=costs, risk=research_risk(), tf=tf)
    mc = monte_carlo(res.trades, 10_000, 500)
    g = gate.check(res.metrics, wf, mc)
    months = max((df.index[-1] - df.index[0]).total_seconds() / (30 * 86400), 1e-9)
    m = dict(res.metrics)
    m["trades_per_month"] = m["trades"] / months
    gross = sum(t.pnl + t.fees for t in res.trades)
    m["fees_share_of_gross"] = float(m["total_fees"] / gross) if gross > 0 else None
    return {"metrics": m, "walk_forward": wf, "monte_carlo": mc, "passed": g["passed"], "failures": g["failures"], "params": st.params}


def run_all(app, symbols: list[str], timeframes: list[str], bars: int = 3000, costs: Costs | None = None,
            gate: ValidationGate | None = None) -> list[dict]:
    costs, gate = costs or Costs(), gate or ValidationGate()
    out = []
    for tf in timeframes:
        for sym in symbols:
            try:
                df, meta = app.market.ohlcv(sym, tf, bars)
            except DataUnavailable as e:
                out.append({"symbol": sym, "timeframe": tf, "error": str(e)})
                continue
            if len(df) < 600:
                out.append({"symbol": sym, "timeframe": tf, "error": f"only {len(df)} bars"})
                continue
            for name, st in REGISTRY.items():
                if tf not in st.timeframes:
                    continue
                r = research_combo(df, name, sym, tf, costs, gate)
                app.store.add(StrategyResearch(strategy=name, exchange=meta.exchange, symbol=sym, timeframe=tf, params=r["params"],
                                               data_start=df.index[0].to_pydatetime(), data_end=df.index[-1].to_pydatetime(),
                                               bars=len(df), source=meta.source, metrics=_clean(r["metrics"]),
                                               walk_forward=_clean(r["walk_forward"]), monte_carlo=_clean(r["monte_carlo"]),
                                               passed=r["passed"], failures=r["failures"]))
                out.append({"strategy": name, "symbol": sym, "timeframe": tf, "passed": r["passed"],
                            "net_return": r["metrics"]["net_return"], "profit_factor": r["metrics"]["profit_factor"],
                            "trades": r["metrics"]["trades"], "source": meta.source})
                log.info("research %s %s %s passed=%s", name, sym, tf, r["passed"])
    return out


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, (np.floating, np.integer)):
        return _clean(o.item())
    return o


__all__ = ["run_all", "research_combo", "TF_SECONDS"]
