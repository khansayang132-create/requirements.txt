"""Backtesting lab.

Fill model (no look-ahead):
- A signal decided at the close of bar i is filled at the OPEN of bar i+1,
  adjusted by half-spread + slippage against the trader, plus taker fee.
- Stop and target are checked from bar i+1 on, using that bar's high/low.
  If both are touched in the same bar the STOP is assumed first (conservative).
- Gaps through a stop fill at the bar's open, not the stop price.
- Partial fills: `fill_ratio` < 1 fills only that fraction of the approved size.
- Funding (perps): `funding_rate_8h` charged on notional per 8 hours held.
- Survivorship: the engine trades only the frames it is given; it does not pick
  symbols. Use symbol lists as they existed at the start of the test.
Sizing comes from RiskEngine, so a backtest obeys the same limits as paper trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import RiskConfig
from .models import Position, Signal, TF_SECONDS
from .risk import RiskEngine, RiskState
from .strategies.base import Strategy


@dataclass
class Costs:
    fee_bps: float = 10.0        # taker fee per side
    spread_bps: float = 2.0      # full spread; half is paid on each fill
    slippage_bps: float = 3.0
    funding_rate_8h: float = 0.0
    fill_ratio: float = 1.0

    def adverse(self, price: float, side: int) -> float:
        return price * (1 + side * (self.spread_bps / 2 + self.slippage_bps) / 1e4)


@dataclass
class Trade:
    symbol: str
    strategy: str
    side: int
    qty: float
    entry_time: pd.Timestamp
    entry: float
    exit_time: pd.Timestamp
    exit: float
    exit_reason: str
    pnl: float
    fees: float
    funding: float
    r_multiple: float

    def as_dict(self):
        d = self.__dict__.copy()
        d["entry_time"], d["exit_time"] = str(self.entry_time), str(self.exit_time)
        return d


@dataclass
class Result:
    trades: list[Trade]
    equity: pd.Series
    metrics: dict = field(default_factory=dict)


def run(df: pd.DataFrame, strategy: Strategy, symbol: str = "BTC/USDT", initial: float = 10_000.0,
        costs: Costs | None = None, risk: RiskConfig | None = None, tf: str = "1h",
        max_hold_bars: int | None = None) -> Result:
    costs = costs or Costs()
    eng = RiskEngine(risk or RiskConfig())
    sig = strategy.signals(df)
    o, h, lo, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    t = df.index
    cash = initial
    st = RiskState(initial, initial, initial, initial)
    pos: Position | None = None
    pos_meta: dict = {}
    trades: list[Trade] = []
    eq = np.empty(len(df))
    bars_per_8h = 8 * 3600 / TF_SECONDS[tf]
    day = week = None
    pending = None  # signal from previous bar close

    for i in range(len(df)):
        ts = t[i]
        d, w = ts.date(), ts.isocalendar()[:2]
        mark = cash + (pos.unrealized(o[i]) if pos else 0.0)
        if d != day:
            st.day_start_equity, day = mark, d
        if w != week:
            st.week_start_equity, week = mark, w

        # 1) fill pending entry at this bar's open
        if pending is not None and pos is None:
            s_side, s_stop, s_tgt, reason = pending
            fill = costs.adverse(o[i], s_side)
            st.equity = mark
            st.peak_equity = max(st.peak_equity, mark)
            sg = Signal(strategy.name, symbol, s_side, fill, s_stop, s_tgt, ts, reason)
            dec = eng.evaluate(sg, st)
            if dec.approved:
                qty = dec.qty * costs.fill_ratio
                fee = fill * qty * costs.fee_bps / 1e4
                cash -= fee
                pos = Position(symbol, s_side, qty, fill, s_stop, s_tgt, strategy.name, ts)
                pos_meta = {"fees": fee, "funding": 0.0, "bars": 0, "risk": abs(fill - s_stop) * qty}
                st.positions = [pos]
        pending = None

        # 2) manage open position within this bar
        if pos is not None:
            pos_meta["bars"] += 1
            if costs.funding_rate_8h:
                f = pos.notional * costs.funding_rate_8h / bars_per_8h * pos.side
                cash -= f
                pos_meta["funding"] += f
            exit_px = reason = None
            if pos.side == 1:
                if lo[i] <= pos.stop:
                    exit_px, reason = min(o[i], pos.stop), "stop"
                elif h[i] >= pos.target:
                    exit_px, reason = max(o[i], pos.target), "target"
            else:
                if h[i] >= pos.stop:
                    exit_px, reason = max(o[i], pos.stop), "stop"
                elif lo[i] <= pos.target:
                    exit_px, reason = min(o[i], pos.target), "target"
            if exit_px is None and max_hold_bars and pos_meta["bars"] >= max_hold_bars:
                exit_px, reason = c[i], "time"
            if exit_px is None and i == len(df) - 1:
                exit_px, reason = c[i], "end_of_data"
            if exit_px is not None:
                fill = costs.adverse(exit_px, -pos.side) if reason != "target" else exit_px
                fee = fill * pos.qty * costs.fee_bps / 1e4
                gross = (fill - pos.entry) * pos.qty * pos.side
                cash += gross - fee
                total_fees = pos_meta["fees"] + fee
                pnl = gross - total_fees - pos_meta["funding"]
                trades.append(Trade(symbol, strategy.name, pos.side, pos.qty, pos.opened_at, pos.entry, ts, fill,
                                    reason, pnl, total_fees, pos_meta["funding"],
                                    pnl / pos_meta["risk"] if pos_meta["risk"] else 0.0))
                pos, st.positions = None, []

        # 3) new signal at this close (filled next bar)
        if pos is None and i < len(df) - 1 and sig["side"].iat[i] != 0:
            pending = (int(sig["side"].iat[i]), float(sig["stop"].iat[i]), float(sig["target"].iat[i]),
                       sig["reason"].iat[i])
        eq[i] = cash + (pos.unrealized(c[i]) if pos else 0.0)
        st.equity = eq[i]
        st.peak_equity = max(st.peak_equity, eq[i])

    equity = pd.Series(eq, index=t, name="equity")
    return Result(trades, equity, metrics(trades, equity, initial, tf))


def metrics(trades: list[Trade], equity: pd.Series, initial: float, tf: str = "1h") -> dict:
    pnl = np.array([tr.pnl for tr in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    rets = equity.pct_change().dropna()
    ann = np.sqrt(365 * 86400 / TF_SECONDS[tf])
    sd = rets.std()
    dn = rets[rets < 0].std()
    peak = equity.cummax()
    mdd = float(((equity - peak) / peak).min()) if len(equity) else 0.0
    years = max((equity.index[-1] - equity.index[0]).total_seconds() / (365 * 86400), 1e-9) if len(equity) > 1 else 1e-9
    net_ret = float(equity.iloc[-1] / initial - 1) if len(equity) else 0.0
    cagr = (1 + net_ret) ** (1 / years) - 1 if net_ret > -1 else -1.0
    streak = best = 0
    for x in pnl:
        streak = streak + 1 if x <= 0 else 0
        best = max(best, streak)
    hold = [(tr.exit_time - tr.entry_time).total_seconds() / 3600 for tr in trades]
    return {
        "trades": int(len(pnl)),
        "net_profit": float(pnl.sum()) if len(pnl) else 0.0,
        "net_return": net_ret,
        "win_rate": float(len(wins) / len(pnl)) if len(pnl) else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else (float("inf") if len(wins) else 0.0),
        "sharpe": float(rets.mean() / sd * ann) if sd and sd > 0 else 0.0,
        "sortino": float(rets.mean() / dn * ann) if dn and dn > 0 else 0.0,
        "max_drawdown": mdd,
        "calmar": float(cagr / -mdd) if mdd < 0 else 0.0,
        "expectancy": float(pnl.mean()) if len(pnl) else 0.0,
        "expectancy_r": float(np.mean([tr.r_multiple for tr in trades])) if trades else 0.0,
        "avg_holding_hours": float(np.mean(hold)) if hold else 0.0,
        "max_consecutive_losses": int(best),
        "total_fees": float(sum(tr.fees for tr in trades)),
    }


def monte_carlo(trades: list[Trade], initial: float = 10_000.0, n: int = 1000, seed: int = 0) -> dict:
    """Resample trade P&L order (bootstrap) to see the drawdown distribution luck can produce."""
    if not trades:
        return {"runs": 0}
    rng = np.random.default_rng(seed)
    pnl = np.array([tr.pnl for tr in trades])
    finals, mdds = [], []
    for _ in range(n):
        path = initial + np.cumsum(rng.choice(pnl, size=len(pnl), replace=True))
        path = np.concatenate([[initial], path])
        peak = np.maximum.accumulate(path)
        mdds.append(float(((path - peak) / peak).min()))
        finals.append(float(path[-1]))
    finals, mdds = np.array(finals), np.array(mdds)
    return {"runs": n, "final_equity_p05": float(np.percentile(finals, 5)), "final_equity_p50": float(np.median(finals)),
            "final_equity_p95": float(np.percentile(finals, 95)), "max_drawdown_p50": float(np.median(mdds)),
            "max_drawdown_p95": float(np.percentile(mdds, 5)), "prob_loss": float((finals < initial).mean())}


def walk_forward(df: pd.DataFrame, strategy_factory, grid: list[dict], n_folds: int = 4, train_frac: float = 0.7,
                 objective: str = "sharpe", **kw) -> dict:
    """Rolling walk-forward: pick params on each train window, score them on the following unseen test window."""
    n = len(df)
    fold = n // n_folds
    out = []
    for k in range(n_folds):
        seg = df.iloc[k * fold:(k + 1) * fold] if k < n_folds - 1 else df.iloc[k * fold:]
        cut = int(len(seg) * train_frac)
        train, test = seg.iloc[:cut], seg.iloc[cut:]
        if len(train) < 250 or len(test) < 50:
            continue
        scored = [(run(train, strategy_factory(p), **kw).metrics.get(objective, 0.0), p) for p in grid]
        best_score, best = max(scored, key=lambda x: x[0])
        res = run(test, strategy_factory(best), **kw)
        out.append({"fold": k, "params": best, "in_sample": best_score, "out_of_sample": res.metrics.get(objective, 0.0),
                    "oos_trades": res.metrics["trades"], "oos_return": res.metrics["net_return"]})
    ins = [f["in_sample"] for f in out]
    oos = [f["out_of_sample"] for f in out]
    return {"folds": out, "mean_in_sample": float(np.mean(ins)) if ins else None,
            "mean_out_of_sample": float(np.mean(oos)) if oos else None,
            "degradation": float(np.mean(ins) - np.mean(oos)) if ins else None}


@dataclass
class ValidationGate:
    """Minimum bar a strategy must clear before it may run in paper or live modes."""
    min_trades: int = 30
    min_profit_factor: float = 1.15
    min_oos_sharpe: float = 0.3
    max_mc_drawdown_p95: float = -0.25   # 95th pct worst drawdown must be better than -25 %
    max_degradation: float = 1.0          # in-sample minus out-of-sample sharpe

    def check(self, m: dict, wf: dict, mc: dict) -> dict:
        fails = []
        if m["trades"] < self.min_trades:
            fails.append(f"only {m['trades']} trades (< {self.min_trades}): statistically weak")
        if m["profit_factor"] < self.min_profit_factor:
            fails.append(f"profit factor {m['profit_factor']:.2f} < {self.min_profit_factor}")
        oos = wf.get("mean_out_of_sample")
        if oos is None or oos < self.min_oos_sharpe:
            fails.append(f"out-of-sample sharpe {oos} < {self.min_oos_sharpe}")
        deg = wf.get("degradation")
        if deg is not None and deg > self.max_degradation:
            fails.append(f"in-sample vs out-of-sample degradation {deg:.2f}: likely overfit")
        if mc.get("runs") and mc["max_drawdown_p95"] < self.max_mc_drawdown_p95:
            fails.append(f"Monte Carlo 95th-pct drawdown {mc['max_drawdown_p95']:.1%} worse than {self.max_mc_drawdown_p95:.0%}")
        return {"passed": not fails, "failures": fails}
