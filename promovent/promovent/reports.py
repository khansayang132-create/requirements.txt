"""Hourly / daily / weekly / monthly reports from recorded data only.

Paper and live are always separate sections. Paper results are labelled "SIMULATED execution on live prices"
and are never added to live results. Every money figure is split into realized P&L (net of fees), fees,
funding, unrealized P&L and net. A section with no data says so instead of showing zeros as results.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
from sqlalchemy import select

from .db.models import Opportunity, PortfolioSnapshot, PositionRow, Report, ResearchFinding, StrategyResearch, TradeReview, utcnow

PERIODS = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}
LABEL = {"paper": "PAPER (simulated execution on live prices)", "live": "LIVE (real exchange orders)"}


def window(period: str, end=None):
    end = pd.Timestamp(end or utcnow())
    end = end.tz_localize("UTC") if end.tzinfo is None else end
    floor = {"hourly": "h", "daily": "D", "weekly": "D", "monthly": "D"}[period]
    end = end.floor(floor)
    return (end - PERIODS[period]).to_pydatetime(), end.to_pydatetime()


def _aware(t):
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t


def _money(app, venue: str, start, end, prices: dict) -> dict:
    with app.store.session() as s:
        closed = s.scalars(select(PositionRow).where(PositionRow.venue != "paper" if venue == "live" else PositionRow.venue == "paper",
                                                     PositionRow.closed_at.is_not(None))).all()
        openp = s.scalars(select(PositionRow).where(PositionRow.venue != "paper" if venue == "live" else PositionRow.venue == "paper",
                                                    PositionRow.closed_at.is_(None))).all()
        closed = [p for p in closed if _aware(start) <= _aware(p.closed_at) < _aware(end)]
        realized = sum(p.pnl or 0 for p in closed)
        fees = sum(p.fees or 0 for p in closed)
        unreal = sum((prices.get(p.symbol, p.entry) - p.entry) * p.qty * p.side for p in openp)
        trades = [{"symbol": p.symbol, "strategy": p.strategy, "entry": p.entry, "exit": p.exit, "reason": p.exit_reason,
                   "net_pnl": round(p.pnl or 0, 2)} for p in closed]
        positions = [{"symbol": p.symbol, "qty": p.qty, "entry": p.entry, "stop": p.stop, "target": p.target,
                      "unrealized": round((prices.get(p.symbol, p.entry) - p.entry) * p.qty * p.side, 2)} for p in openp]
    wins = [t for t in trades if t["net_pnl"] > 0]
    return {"label": LABEL[venue], "realized_pnl_net": round(realized, 2), "fees": round(fees, 2), "funding": 0.0,
            "gross_pnl": round(realized + fees, 2), "unrealized_pnl": round(unreal, 2), "net_total": round(realized + unreal, 2),
            "closed_trades": len(trades), "win_rate": round(len(wins) / len(trades), 3) if trades else None,
            "trades": trades, "open_positions": positions,
            "funding_note": "spot only: no funding costs"}


def generate(app, period: str, end=None, prices: dict | None = None) -> dict:
    start, end = window(period, end)
    prices = prices or {}
    step = app.store.kv_get("autopilot_last_step") or {}
    c = {"period": period, "start": str(start), "end": str(end), "generated_at": str(utcnow()),
         "mode": app.settings.mode.value, "data_source": app.source,
         "paper": _money(app, "paper", start, end, prices), "live": _money(app, "live", start, end, prices),
         "autopilot": {"last_decision": step.get("decision"), "gates": step.get("gates"), "approved": step.get("approved", [])}}
    with app.store.session() as s:
        ops = s.scalars(select(Opportunity).where(Opportunity.ts >= start, Opportunity.ts < end)).all()
        c["opportunities"] = {"total": len(ops), "taken": sum(o.decision == "taken" for o in ops),
                              "rejected": sum(o.decision == "rejected" for o in ops),
                              "top_rejection_reasons": pd.Series([o.reason.split(":")[0] for o in ops if o.decision == "rejected"]
                                                                 ).value_counts().head(5).to_dict() if ops else {}}
        if period in ("daily", "weekly", "monthly"):
            st = app.broker.state
            c["risk"] = {"equity_paper": round(app.broker.equity(prices), 2), "drawdown": round(app.risk.drawdown(st), 4),
                         "daily_loss": round(app.risk.daily_loss(st), 4), "weekly_loss": round(app.risk.weekly_loss(st), 4),
                         "lockouts": app.risk.lockouts(st), "kill_switch": st.kill_switch}
        if period in ("weekly", "monthly"):
            sr = s.scalars(select(StrategyResearch).where(StrategyResearch.ts >= start, StrategyResearch.ts < end)).all()
            c["strategy_research"] = {"combos_tested": len(sr), "passed": sum(r.passed for r in sr),
                                      "passed_combos": [f"{r.strategy} {r.symbol} {r.timeframe}" for r in sr if r.passed],
                                      "best_by_profit_factor": sorted(({"combo": f"{r.strategy} {r.symbol} {r.timeframe}",
                                                                        "pf": (r.metrics or {}).get("profit_factor"),
                                                                        "net_return": (r.metrics or {}).get("net_return")} for r in sr
                                                                       if (r.metrics or {}).get("profit_factor") is not None),
                                                                      key=lambda x: -x["pf"])[:5]}
            rv = s.scalars(select(TradeReview).where(TradeReview.ts >= start, TradeReview.ts < end)).all()
            c["trade_reviews"] = {"n": len(rv), "hypothesis_correct": sum(r.evaluation.get("hypothesis") == "correct" for r in rv),
                                  "profitable_but_not_as_predicted": sum(bool(r.evaluation.get("lucky")) for r in rv),
                                  "regime_changed": sum(bool(r.evaluation.get("regime_changed")) for r in rv),
                                  "execution_issues": sum(not r.evaluation.get("execution_ok", True) for r in rv)}
            from .ml.learner import monitor
            c["model_evaluation"] = monitor(app)
            fnd = s.scalars(select(ResearchFinding).where(ResearchFinding.ts >= start, ResearchFinding.ts < end)).all()
            c["research_findings"] = [{"area": f.area, "title": f.title, "conclusion": f.conclusion} for f in fnd]
        if period == "monthly":
            snaps = s.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.ts >= start, PortfolioSnapshot.ts < end,
                                                              PortfolioSnapshot.venue == "paper")).all()
            eq = pd.Series([x.equity for x in snaps]) if snaps else pd.Series(dtype=float)
            c["portfolio_paper"] = {"snapshots": len(snaps), "start_equity": float(eq.iloc[0]) if len(eq) else None,
                                    "end_equity": float(eq.iloc[-1]) if len(eq) else None,
                                    "max_drawdown": float((eq / eq.cummax() - 1).min()) if len(eq) else None}
    md = markdown(c)
    with app.store.session() as s:
        existing = s.scalar(select(Report).where(Report.period == period, Report.start == start))
        if existing:
            existing.content, existing.markdown, existing.end = c, md, end
        else:
            s.add(Report(period=period, start=start, end=end, content=c, markdown=md))
    return c


def markdown(c: dict) -> str:
    L = [f"# Promovent {c['period']} report", f"{c['start']} → {c['end']} · mode `{c['mode']}` · market data `{c['data_source']}`", ""]
    for v in ("live", "paper"):
        m = c[v]
        L += [f"## {m['label']}"]
        if not m["closed_trades"] and not m["open_positions"]:
            L += ["No trades and no open positions in this period.", ""]
            continue
        L += [f"- Realized P&L (net of fees): {m['realized_pnl_net']:+.2f}", f"- Fees: {m['fees']:.2f}",
              f"- Funding: {m['funding']:.2f} ({m['funding_note']})", f"- Unrealized P&L: {m['unrealized_pnl']:+.2f}",
              f"- Net (realized + unrealized): {m['net_total']:+.2f}", f"- Closed trades: {m['closed_trades']}"
              + (f", win rate {m['win_rate']:.0%}" if m["win_rate"] is not None else ""), ""]
    a = c["autopilot"]
    L += ["## Autopilot", f"- Last decision: {a['last_decision'] or 'no step recorded yet'}",
          f"- Approved combos: {', '.join(x['strategy'] + ' ' + x['symbol'] + ' ' + x['timeframe'] for x in a['approved']) or 'none'}",
          f"- Opportunities: {c['opportunities']['total']} (taken {c['opportunities']['taken']}, rejected {c['opportunities']['rejected']})", ""]
    if "risk" in c:
        r = c["risk"]
        L += ["## Risk", f"- Paper equity {r['equity_paper']:.2f}, drawdown {r['drawdown']:.2%}, daily loss {r['daily_loss']:.2%}, "
              f"weekly loss {r['weekly_loss']:.2%}",
              f"- Lockouts: {'; '.join(r['lockouts']) or 'none'}; kill switch {'ON' if r['kill_switch'] else 'off'}", ""]
    if "strategy_research" in c:
        sr = c["strategy_research"]
        L += ["## Strategy research", f"- Combos tested: {sr['combos_tested']}, passed: {sr['passed']}"
              + (f" ({', '.join(sr['passed_combos'])})" if sr["passed_combos"] else ""), ""]
        me = c["model_evaluation"]
        L += ["## Models", f"- {me.get('status')}", ""]
    if c.get("research_findings"):
        L += ["## Research findings"] + [f"- {f['area']}: {f['title']}: **{f['conclusion']}**" for f in c["research_findings"]] + [""]
    return "\n".join(L)
