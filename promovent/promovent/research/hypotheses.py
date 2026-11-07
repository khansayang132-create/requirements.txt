"""Hypothesis tests for research areas A-L, on data the system can actually fetch.

Every test returns a finding dict with: area, title, hypothesis, source, data_window, methodology, result,
conclusion (supported | not_supported | inconclusive | not_tested), summary, limitations, data_source.
Pure functions take data; `run_all` fetches live data and stores the findings. Statistics use simple,
stated methods (t-statistics, autocorrelation bands, variance ratios); no multiple-testing correction is
applied across findings, which the limitations say.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
import numpy as np
import pandas as pd

from ..backtest import Costs, run
from ..config import research_risk
from ..db.models import ResearchFinding
from ..strategies import get_strategy
from ..ta.orderflow import book_metrics, slippage_estimate
from . import sources

log = logging.getLogger("promovent.research")


def F(area, title, hypothesis, source, window, method, result, conclusion, summary, limitations, data_source="live"):
    return {"area": area, "title": title, "hypothesis": hypothesis, "source": source, "data_window": window,
            "methodology": method, "result": result, "conclusion": conclusion, "summary": summary,
            "limitations": limitations, "data_source": data_source}


def _win(idx) -> str:
    return f"{idx[0]:%Y-%m-%d %H:%M} -> {idx[-1]:%Y-%m-%d %H:%M} UTC"


def _r(x, n=4):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


# --- A: market structure ---------------------------------------------------------------------------
def a_volume_concentration(tickers: list[dict], source: str) -> dict:
    vols = np.array([t["quote_volume_24h"] for t in tickers], float)
    tot = vols.sum()
    share = vols / tot if tot else vols
    top = [(t["symbol"], round(float(s), 4)) for t, s in zip(tickers[:5], share[:5], strict=False)]
    hhi = float((share ** 2).sum())
    btc_eth = sum(s for t, s in zip(tickers, share, strict=False) if t["symbol"] in ("BTC/USDT", "ETH/USDT"))
    return F("A", "Spot volume concentration (USDT pairs)", "BTC and ETH account for more than half of USDT spot volume.",
             source, "24h snapshot " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "Share of 24h quote volume across all listed USDT spot pairs (stablecoins excluded); Herfindahl index.",
             {"pairs": len(tickers), "btc_eth_share": round(btc_eth, 4), "top5": top, "hhi": round(hhi, 4)},
             "supported" if btc_eth > 0.5 else "not_supported",
             f"BTC+ETH = {btc_eth:.1%} of {len(tickers)} pairs' volume; HHI {hhi:.3f}.",
             "One exchange and one 24h window; volume includes wash trading where it exists; spot only.")


# --- B: BTC/ETH behaviour --------------------------------------------------------------------------
def b_volatility_clustering(df: pd.DataFrame, symbol: str, source: str) -> dict:
    r = np.log(df["close"]).diff().dropna()
    n = len(r)
    band = 2 / np.sqrt(n)
    ac_r = [float(r.autocorr(k)) for k in (1, 2, 3)]
    ac_abs = [float(r.abs().autocorr(k)) for k in (1, 2, 3)]
    kurt = float(r.kurt())
    ok = all(a > band for a in ac_abs) and all(abs(a) < 3 * band for a in ac_r)
    return F("B", f"{symbol} volatility clustering and fat tails",
             "Hourly absolute returns are positively autocorrelated (volatility clusters) while signed returns are not, "
             "and returns have fat tails.", source, _win(df.index),
             f"Autocorrelation of log returns and |log returns| at lags 1-3 vs the ±2/sqrt(n) band (n={n}); excess kurtosis.",
             {"n": n, "band": round(band, 4), "acf_returns": [round(a, 4) for a in ac_r], "acf_abs_returns": [round(a, 4) for a in ac_abs],
              "excess_kurtosis": round(kurt, 2)},
             "supported" if ok and kurt > 0 else "not_supported",
             f"|r| autocorrelation {ac_abs[0]:.3f} (band {band:.3f}); signed {ac_r[0]:.3f}; excess kurtosis {kurt:.1f}.",
             "Four months of hourly data from one venue; the band assumes i.i.d. returns.")


# --- C: altcoin dynamics ---------------------------------------------------------------------------
def c_alt_beta(frames: dict[str, pd.DataFrame], source: str) -> dict:
    btc = np.log(frames["BTC/USDT"]["close"]).diff()
    rows = {}
    for s, df in frames.items():
        if s == "BTC/USDT":
            continue
        r = np.log(df["close"]).diff()
        j = pd.concat([r, btc], axis=1, join="inner").dropna()
        if len(j) < 200:
            continue
        cov = np.cov(j.iloc[:, 0], j.iloc[:, 1])
        rows[s] = {"beta": round(float(cov[0, 1] / cov[1, 1]), 3), "corr": round(float(j.corr().iloc[0, 1]), 3), "n": len(j)}
    betas = [v["beta"] for v in rows.values()]
    share = float(np.mean([b > 1 for b in betas])) if betas else 0
    return F("C", "Altcoin beta and correlation to BTC (1h returns)", "Most large altcoins have beta > 1 to BTC.",
             source, _win(frames["BTC/USDT"].index), "OLS beta = cov(alt, BTC) / var(BTC) and Pearson correlation of hourly log returns.",
             {"by_symbol": rows, "share_beta_gt_1": round(share, 3)},
             "supported" if share > 0.5 else "not_supported", f"{share:.0%} of {len(rows)} altcoins have beta > 1.",
             "Betas are unstable across regimes; one window; no confidence intervals reported.")


# --- E: order book liquidity / execution ------------------------------------------------------------
def e_book_depth(books: dict, source: str, sizes=(1_000, 10_000, 100_000)) -> dict:
    rows = {}
    for s, b in books.items():
        m = book_metrics(b)
        mid = m["mid"]
        rows[s] = {"spread_bps": round(m["spread_bps"], 3), **{
            f"slip_bps_buy_${n:,}": _r(slippage_estimate(b, 1, n / mid).get("slippage_bps"), 2) if
            slippage_estimate(b, 1, n / mid)["complete"] else "book too thin" for n in sizes}}
    return F("E", "Visible order-book cost of a market buy", "A $100k market buy costs under 5 bps of slippage in BTC and ETH "
             "but more in smaller pairs.", source, "snapshot " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "Walk the visible top-50 levels of each book for $1k / $10k / $100k buys; slippage vs mid.", rows,
             "supported" if all(isinstance(rows.get(s, {}).get("slip_bps_buy_$100,000"), float) and
                                rows[s]["slip_bps_buy_$100,000"] < 5 for s in ("BTC/USDT", "ETH/USDT") if s in rows) else "not_supported",
             "; ".join(f"{s}: {v['slip_bps_buy_$100,000']} bps for $100k" for s, v in rows.items()),
             "Single snapshot; visible liquidity can be pulled; hidden/iceberg orders and refills are not seen.")


# --- F: funding and open interest ---------------------------------------------------------------------
def f_funding_extremes(funding: pd.Series, price: pd.DataFrame, symbol: str, source: str, horizon_h: int = 24) -> dict:
    close = price["close"]
    fwd = {}
    for t, rate in funding.items():
        i = close.index.searchsorted(t)
        if i + horizon_h < len(close):
            fwd[t] = (rate, float(np.log(close.iloc[i + horizon_h] / close.iloc[i])))
    d = pd.DataFrame(fwd, index=["rate", "fwd"]).T.dropna()
    if len(d) < 60:
        return F("F", f"{symbol} funding extremes vs next {horizon_h}h", "Extreme funding precedes mean reversion.", source,
                 "insufficient overlap", "n/a", {"n": len(d)}, "inconclusive", "Not enough aligned observations.",
                 "Needs more funding history.")
    hi, lo = d["rate"].quantile(0.9), d["rate"].quantile(0.1)
    top, bot, rest = d[d.rate >= hi].fwd, d[d.rate <= lo].fwd, d.fwd

    def t(a, b):
        se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        return float((a.mean() - b.mean()) / se) if se > 0 else 0.0
    t_top, t_bot = t(top, rest), t(bot, rest)
    supported = t_top < -2 and t_bot > 2
    return F("F", f"{symbol} funding-rate extremes vs next {horizon_h}h spot return",
             "When funding is in its top decile (crowded longs) the next-24h return is below average, and above average after "
             "the bottom decile.", source, _win(d.index),
             f"Realized 8h funding (OKX {symbol.replace('/', '-')}-SWAP) aligned to the next spot close and the close {horizon_h}h later; "
             "Welch t-statistic of decile mean vs all observations.",
             {"n": len(d), "top_decile_mean_fwd": _r(top.mean(), 5), "bottom_decile_mean_fwd": _r(bot.mean(), 5),
              "all_mean_fwd": _r(rest.mean(), 5), "t_top_vs_all": round(t_top, 2), "t_bottom_vs_all": round(t_bot, 2)},
             "supported" if supported else ("inconclusive" if abs(t_top) < 2 and abs(t_bot) < 2 else "not_supported"),
             f"Top-decile funding: next-{horizon_h}h mean {top.mean():+.3%} (t={t_top:.1f}); bottom decile {bot.mean():+.3%} (t={t_bot:.1f}).",
             "Overlapping 24h windows inflate t-statistics; ~3 months of funding; one venue.")


def f_open_interest(oi: pd.DataFrame, price: pd.DataFrame, ccy: str, source: str) -> dict:
    c = price["close"].resample("1D").last().dropna()
    j = pd.concat([oi["oi_usd"].pct_change().rename("doi"), np.log(c).diff().shift(-1).rename("next_ret")], axis=1).dropna()
    if len(j) < 30:
        return F("F", f"{ccy} OI change vs next-day return", "OI growth predicts next-day returns.", source, "insufficient data",
                 "n/a", {"n": len(j)}, "inconclusive", "Too few days.", "Needs longer OI history.")
    corr = float(j.corr().iloc[0, 1])
    tstat = corr * np.sqrt((len(j) - 2) / (1 - corr ** 2))
    return F("F", f"{ccy} open-interest change vs next-day return", "Daily change in open interest has predictive correlation with "
             "the next day's spot return.", source, _win(j.index),
             "Pearson correlation of daily % change in OKX contract open interest (USD) with the next day's log return; t-test.",
             {"n": len(j), "corr": round(corr, 4), "t": round(float(tstat), 2)},
             "supported" if abs(tstat) > 2 else "not_supported", f"corr {corr:+.3f} (t={tstat:.2f}, n={len(j)}).",
             "Daily granularity; OKX contracts only; correlation is not causation.")


# --- G: sentiment ------------------------------------------------------------------------------------
def g_fear_greed(fg: pd.Series, daily: pd.DataFrame, source: str, horizon_d: int = 7) -> dict:
    c = daily["close"]
    fg = fg.copy()
    fg.index = fg.index.floor("D")
    j = pd.concat([fg.rename("fg"), (np.log(c).shift(-horizon_d) - np.log(c)).rename("fwd")], axis=1).dropna()
    fear, greed = j[j.fg < 25].fwd, j[j.fg > 75].fwd
    if len(fear) < 15:  # the fear-side hypothesis needs only fear days; greed is reported for context
        return F("G", f"Fear & Greed extremes vs next {horizon_d}d BTC return", "Extreme fear precedes above-average returns.",
                 source, _win(j.index) if len(j) else "n/a", "Bucket days by index value; compare forward return means.",
                 {"n": len(j), "fear_days": len(fear), "greed_days": len(greed)}, "inconclusive",
                 f"Too few extreme days (fear {len(fear)}, greed {len(greed)}).", "Short history window.")
    se = np.sqrt(fear.var(ddof=1) / len(fear) + j.fwd.var(ddof=1) / len(j))
    t = float((fear.mean() - j.fwd.mean()) / se) if se > 0 else 0
    return F("G", f"Fear & Greed extremes vs next {horizon_d}d BTC return", "Days of extreme fear (index < 25) are followed by "
             "above-average 7-day BTC returns.", source, _win(j.index),
             "alternative.me Crypto Fear & Greed index (daily) joined to OKX BTC/USDT daily closes; Welch t of fear-day forward return vs all days.",
             {"n": len(j), "fear_days": len(fear), "greed_days": len(greed), "fear_mean_fwd": _r(fear.mean(), 5),
              "greed_mean_fwd": _r(greed.mean(), 5), "all_mean_fwd": _r(j.fwd.mean(), 5), "t_fear_vs_all": round(t, 2)},
             "supported" if t > 2 else "not_supported" if t < -2 else "inconclusive",
             f"Extreme-fear days: next-{horizon_d}d mean {fear.mean():+.2%} vs {j.fwd.mean():+.2%} overall (t={t:.2f}).",
             "Overlapping windows; one market cycle; the index itself is built partly from price momentum.")


def h_onchain_not_tested() -> dict:
    return F("H", "On-chain exchange flows vs returns", "Net exchange inflows precede negative returns.", "none",
             "n/a", "Would join Whale Alert / Etherscan exchange flows to forward returns.", {}, "not_tested",
             "Not tested: no WHALE_ALERT_API_KEY or ETHERSCAN_API_KEY configured, and on-chain hosts are not allow-listed.",
             "Requires provider keys and network access.", data_source="none")


# --- I: quantitative technique --------------------------------------------------------------------------
def i_variance_ratio(df: pd.DataFrame, symbol: str, source: str, qs=(4, 24)) -> dict:
    r = np.log(df["close"]).diff().dropna().to_numpy()
    n, var1 = len(r), r.var(ddof=1)
    res = {}
    for q in qs:
        rq = pd.Series(r).rolling(q).sum().dropna().to_numpy()
        vr = rq.var(ddof=1) / (q * var1)
        z = (vr - 1) / np.sqrt(2 * (2 * q - 1) * (q - 1) / (3 * q * n))
        res[f"q{q}"] = {"vr": round(float(vr), 4), "z": round(float(z), 2)}
    sig = [k for k, v in res.items() if abs(v["z"]) > 2]
    return F("I", f"{symbol} random-walk variance-ratio test (1h)", "Hourly returns deviate from a random walk "
             "(VR<1 mean reversion, VR>1 momentum).", source, _win(df.index),
             "Lo-MacKinlay variance ratio with overlapping q-period sums, homoskedastic z-statistic.", res,
             "supported" if sig else "not_supported",
             "; ".join(f"q={k[1:]}: VR {v['vr']:.3f} (z={v['z']:.1f})" for k, v in res.items()),
             "Homoskedastic z overstates significance under volatility clustering (see area B).")


# --- K: execution costs ----------------------------------------------------------------------------------
def k_cost_drag(df: pd.DataFrame, symbol: str, tf: str, strategies: list[str], source: str, costs: Costs) -> dict:
    rows, flipped = {}, 0
    for s in strategies:
        gross = run(df, get_strategy(s), symbol, 10_000, Costs(0, 0, 0), risk=research_risk(), tf=tf).metrics
        net = run(df, get_strategy(s), symbol, 10_000, costs, risk=research_risk(), tf=tf).metrics
        rows[s] = {"trades": net["trades"], "return_no_costs": round(gross["net_return"], 4), "return_with_costs": round(net["net_return"], 4)}
        flipped += gross["net_return"] > 0 >= net["net_return"]
    return F("K", f"Transaction-cost drag ({symbol} {tf})", "Realistic costs turn otherwise profitable strategies unprofitable.",
             source, _win(df.index), f"Same backtest with zero costs vs fee {costs.fee_bps} bps/side, spread {costs.spread_bps} bps, "
             f"slippage {costs.slippage_bps} bps.", {"by_strategy": rows, "flipped_to_loss": flipped},
             "supported" if flipped else "not_supported",
             f"{flipped} of {len(rows)} strategies profitable before costs became unprofitable after.",
             "Fixed cost model; maker rebates and fee tiers not modelled.")


# --- L: risk ---------------------------------------------------------------------------------------------
def l_risk_of_ruin(r_multiples: list[float], source_desc: str, levels=(0.0025, 0.005, 0.01), n_trades: int = 200, runs: int = 2000,
                   seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    rr = np.array(r_multiples, float)
    out = {}
    for f in levels:
        dds = []
        for _ in range(runs):
            eq = np.cumprod(1 + f * rng.choice(rr, n_trades))
            dds.append(float((eq / np.maximum.accumulate(eq) - 1).min()))
        out[f"{f:.2%}"] = {"median_max_dd": round(float(np.median(dds)), 4), "p95_max_dd": round(float(np.percentile(dds, 5)), 4),
                           "p_dd_worse_than_15pct": round(float(np.mean(np.array(dds) < -0.15)), 4)}
    return F("L", "Drawdown risk by risk-per-trade", "At 0.25 % risk per trade the 95th-percentile drawdown over 200 trades "
             "stays under 15 %, while 1 % does not.", source_desc, f"{len(rr)} historical trades",
             f"Bootstrap {runs} sequences of {n_trades} trades from the observed R-multiples; compounded equity; max drawdown.",
             out, "supported" if out["0.25%"]["p95_max_dd"] > -0.15 and out["1.00%"]["p95_max_dd"] < -0.15 else "not_supported",
             "; ".join(f"{k}: p95 drawdown {v['p95_max_dd']:.1%}" for k, v in out.items()),
             "Assumes trades are independent and the past R distribution persists; these strategies have negative expectancy.")


# --- runner ---------------------------------------------------------------------------------------------
def run_all(app, http: httpx.Client | None = None, mission_id: str | None = None) -> list[dict]:
    from ..autopilot.universe import parse_okx_tickers
    from ..data.exchanges import OKX
    http = http or httpx.Client(timeout=15)
    okx_src = "OKX public REST v5 (https://www.okx.com/api/v5)"
    out = []

    def keep(f):
        out.append(f)
        app.store.add(ResearchFinding(**f, mission_id=mission_id))

    def attempt(area, fn):
        try:
            keep(fn())
        except Exception as e:  # a failed test is recorded as not tested, never silently dropped
            log.exception("research %s failed", area)
            keep(F(area, f"{area}: test could not run", "-", "-", "-", "-", {"error": str(e)[:300]}, "not_tested",
                   f"Not tested: {type(e).__name__}: {str(e)[:200]}", "Data unavailable at research time.", data_source="none"))

    core = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "LINK/USDT", "AVAX/USDT"]
    frames = {}
    for s in core:
        try:
            frames[s] = app.market.ohlcv(s, "1h", 3000)[0]
        except Exception as e:
            log.warning("research data %s: %s", s, e)
    attempt("A", lambda: a_volume_concentration(parse_okx_tickers(http.get("https://www.okx.com/api/v5/market/tickers",
                                                                                params={"instType": "SPOT"}).json()),
                                                okx_src + " /market/tickers?instType=SPOT"))
    for s in ("BTC/USDT", "ETH/USDT"):
        if s in frames:
            attempt("B", lambda s=s: b_volatility_clustering(frames[s], s, okx_src + " /market/history-candles 1H"))
    if "BTC/USDT" in frames:
        attempt("C", lambda: c_alt_beta(frames, okx_src + " /market/history-candles 1H"))
    attempt("E", lambda: e_book_depth({s: OKX(http).book(s, 50)[0] for s in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT")},
                                      okx_src + " /market/books sz=50"))
    for s in ("BTC/USDT", "ETH/USDT"):
        if s in frames:
            attempt("F", lambda s=s: f_funding_extremes(sources.okx_funding_history(http, s.replace("/", "-") + "-SWAP"), frames[s], s,
                                                        okx_src + " /public/funding-rate-history + /market/history-candles"))
    attempt("F", lambda: f_open_interest(sources.okx_open_interest_history(http, "BTC"), app.market.ohlcv("BTC/USDT", "1d", 400)[0],
                                         "BTC", okx_src + " /rubik/stat/contracts/open-interest-volume + daily candles"))
    attempt("G", lambda: g_fear_greed(sources.fear_greed_history(http, 400), app.market.ohlcv("BTC/USDT", "1d", 400)[0],
                                      "alternative.me /fng (Crypto Fear & Greed) + " + okx_src + " daily candles"))
    keep(h_onchain_not_tested())
    if "BTC/USDT" in frames:
        attempt("I", lambda: i_variance_ratio(frames["BTC/USDT"], "BTC/USDT", okx_src + " /market/history-candles 1H"))
        strats = ["trend_following", "breakout_retest", "momentum_continuation", "market_structure", "volatility_expansion"]
        attempt("K", lambda: k_cost_drag(frames["BTC/USDT"], "BTC/USDT", "1h", strats, okx_src + " 1H candles", Costs()))

        def l_test():
            rs = []
            for s in strats:
                rs += [t.r_multiple for t in run(frames["BTC/USDT"], get_strategy(s), "BTC/USDT", 10_000, Costs(), risk=research_risk(), tf="1h").trades]
            return l_risk_of_ruin(rs, "Promovent backtests of 5 strategies on " + okx_src + " BTC/USDT 1H")
        attempt("L", l_test)
    return out
