"""72-hour research mission, then continuous research.

State (kv `research_mission`): id, started_at, ends_at, cycles, last_cycle_at. While the mission runs, a full
cycle (strategy research on live history + hypothesis tests A-L + ML retrain) runs every `interval_h` hours
(default 6 => ~12 cycles in 72 h). Each cycle's findings are stored with the mission id, so consistency of a
conclusion across cycles can be checked. After 72 h a summary finding is written and research continues daily.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import timedelta

from sqlalchemy import select

from ..db.models import ResearchFinding, utcnow
from . import hypotheses, strategy_researcher


def state(app) -> dict | None:
    return app.store.kv_get("research_mission")


def start(app, hours: float = 72, interval_h: float = 6) -> dict:
    now = utcnow()
    st = {"id": "m-" + uuid.uuid4().hex[:8], "started_at": str(now), "ends_at": str(now + timedelta(hours=hours)),
          "interval_h": interval_h, "cycles": 0, "last_cycle_at": None, "status": "running"}
    app.store.kv_set("research_mission", st)
    return st


def due(st: dict, now) -> bool:
    import pandas as pd
    if st["last_cycle_at"] is None:
        return True
    interval = st["interval_h"] if st["status"] == "running" else 24
    return pd.Timestamp(now) - pd.Timestamp(st["last_cycle_at"]) >= pd.Timedelta(hours=interval)


def cycle(app, symbols: list[str], timeframes: list[str], retrain=None) -> dict:
    st = state(app) or start(app)
    now = utcnow()
    strat = strategy_researcher.run_all(app, symbols, timeframes)
    passed = [r for r in strat if r.get("passed")]
    found = hypotheses.run_all(app, mission_id=st["id"])
    d = hypotheses.F("D", "Technical strategies on live history (this cycle)",
                     "At least one strategy/symbol/timeframe passes the validation gate on live data.",
                     f"Promovent strategy research on {app.market.exchange} history", f"{len(strat)} combos",
                     "Backtest with costs + 3-fold walk-forward + Monte Carlo + validation gate (see backtest.ValidationGate).",
                     {"tested": len([r for r in strat if "passed" in r]), "passed": [f"{r['strategy']} {r['symbol']} {r['timeframe']}" for r in passed],
                      "errors": [r for r in strat if "error" in r][:10]},
                     "supported" if passed else "not_supported",
                     f"{len(passed)} of {len([r for r in strat if 'passed' in r])} combos passed.",
                     "Short history; gate thresholds are a policy choice; passing is not a guarantee of future returns.")
    app.store.add(ResearchFinding(**d, mission_id=st["id"]))
    ml = None
    if retrain:
        try:
            ml = retrain()
            j = hypotheses.F("J", "ML models vs base rate (this cycle)", "A model beats the base-rate Brier score out of sample.",
                             f"{app.market.exchange} history, Promovent ML engine", f"{ml['rows']} rows",
                             "Purged expanding walk-forward, 4 folds; LightGBM, XGBoost, RandomForest, statistical baseline.",
                             {"results": ml["results"], "promoted": ml["promoted"]},
                             "supported" if ml["promoted"] else "not_supported",
                             "Promoted " + ml["promoted"]["kind"] if ml["promoted"] else "No model beat the base rate; none promoted.",
                             "Short history; 12-bar horizon only; features are price/volume only.", data_source=ml["source"])
            app.store.add(ResearchFinding(**j, mission_id=st["id"]))
        except Exception as e:
            ml = {"error": str(e)}
    st["cycles"] += 1
    st["last_cycle_at"] = str(now)
    import pandas as pd
    if st["status"] == "running" and pd.Timestamp(now) >= pd.Timestamp(st["ends_at"]):
        st["status"] = "completed"
        summarize(app, st)
    app.store.kv_set("research_mission", st)
    return {"mission": st, "strategy_results": len(strat), "passed": len(passed), "findings": len(found) + 1, "ml": ml}


def summarize(app, st: dict) -> None:
    with app.store.session() as s:
        rows = s.scalars(select(ResearchFinding).where(ResearchFinding.mission_id == st["id"])).all()
        by = {}
        for r in rows:
            by.setdefault((r.area, r.title.split(" (")[0]), []).append(r.conclusion)
    stable = {f"{a}: {t}": Counter(c).most_common(1)[0] + (len(c),) for (a, t), c in by.items()}
    f = hypotheses.F("I", f"72-hour mission {st['id']} summary", "Conclusions are stable across research cycles.",
                     "Promovent research findings table", f"{st['started_at']} -> {st['ends_at']}",
                     "For each finding title, the most common conclusion and how many cycles agreed.",
                     {k: {"conclusion": v[0], "agree": v[1], "cycles": v[2]} for k, v in stable.items()},
                     "supported" if all(v[1] == v[2] for v in stable.values()) else "inconclusive",
                     f"{st['cycles']} cycles; {sum(v[1] == v[2] for v in stable.values())} of {len(stable)} findings identical in every cycle.",
                     "Cycles share most of their data window, so agreement overstates independence.")
    app.store.add(ResearchFinding(**f, mission_id=st["id"]))
