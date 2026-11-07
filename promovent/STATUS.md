# Promovent STATUS

Completion gate in the repo's style: **VERIFIED** (test or run shown), **IMPLEMENTED** (code exists, not proven
against the real thing), **BLOCKED**, **NOT IMPLEMENTED**. Updated 2026-11-07.

**Bottom line:** the research and paper-trading core works and is tested. It has **never seen real market data**:
the build sandbox's proxy returns 403 for every exchange host. Nothing here has been deployed. Do not trade real
money with it.

## Acceptance checklist (spec section 20)

| # | Requirement | State | Evidence / gap |
|---|---|---|---|
| 1 | Market data integration | **IMPLEMENTED, live BLOCKED** | 4 adapters; parsers tested against hand-built responses in each exchange's documented format (`tests/test_exchanges.py`). Live calls: `binance/bybit/okx/coinbase: ProxyError: 403 Forbidden` from this sandbox. Not run against a real exchange. REST polling only; **WebSockets NOT IMPLEMENTED**. |
| 2 | Technical analysis | **VERIFIED** | `test_indicators.py`, `test_structure.py`; no-repaint guard over structure, regime and all 9 strategies (`test_no_lookahead.py`). |
| 3 | Market scanner | **VERIFIED (synthetic)** | `/api/scan` in `test_api.py` and the rendered dashboard. |
| 4 | Opportunity scoring | **VERIFIED** | Weights sum to 100; missing factors score 0 and are listed. In the scanner, order flow, liquidity, sentiment and MTF have no data feed, so scores top out near 60. |
| 5 | Strategy engines | **VERIFIED for 9 of 12** | A, B, C, D, E, F, J, plus K (swing) and L (scalping) as parameter variants of A and D. G (stat-arb z-score) and I (funding/basis) are analytics functions only; H is a price monitor. No strategy has shown an edge: on synthetic data all are near break-even or losing, which says nothing about real markets either way. |
| 6 | Risk engine | **VERIFIED** | 19 tests in `test_risk.py`: sizing, notional cap, lockouts, kill switch, correlation, heat, drawdown throttle, config hard rules, live gate. |
| 7 | Backtesting | **VERIFIED** | Fill model tests (next open, stop-first, gaps, costs, partial fills, funding, equity reconciles with trades), Monte Carlo, walk-forward, validation gate. Tick-level simulation **NOT IMPLEMENTED** (OHLCV only). Bayesian optimization **NOT IMPLEMENTED** (grid search in walk-forward). |
| 8 | Paper trading | **VERIFIED (synthetic prices)** | `test_paper.py`: mode gate, validation gate, duplicates, stop closes, kill switch, partial fills, audit. There is no background loop that marks positions to live prices: `on_price` must be driven by a caller. |
| 9 | Portfolio monitoring | **VERIFIED (paper)** | `/api/portfolio`: equity, P&L, heat, drawdown, lockouts. Exposure-by-strategy and rebalancing recommendations **NOT IMPLEMENTED**. |
| 10 | Dashboard | **VERIFIED (synthetic)** | `design-check` at 390 and 1440 px, dark: 0 errors, 0 warnings. Screenshots in `docs/screenshots/` show SYNTHETIC data and are labeled so. Single HTML page served by FastAPI, not Next.js/TypeScript/Tailwind. |
| 11 | Security tests | **VERIFIED (scope below)** | API keys (constant-time compare, 24+ chars), roles, rate limit, input validation, audit log, static checks for no withdrawal/transfer code, no signed requests, no hard-coded secrets (`test_security.py`, `test_api.py`). No penetration test. Exchange credentials are not stored at all, so credential encryption is not needed yet and **NOT IMPLEMENTED**. Sessions/login **NOT IMPLEMENTED** (API keys only). |
| 12 | Deployment | **NOT VERIFIED** | Dockerfile written, not built here. No deployment URL exists. |

## Not implemented (spec items)

- Live order execution (modes 4 and 5): refused with `LiveTradingUnavailable`. Needs signed exchange clients, order
  state reconciliation and its own test plan before it should exist.
- WebSocket feeds, tick data, liquidation feeds, Fear & Greed fetch, news/social sentiment, on-chain whale tracking
  (needs a paid provider such as Glassnode/Arkham/Whale Alert).
- Telegram/email alert delivery (alerts go to the dashboard and the `alerts` table).
- PostgreSQL / TimescaleDB / Redis (SQLite now; schema in `migrations/`).
- ML: PyTorch models, feature importance, drift detection, Bayesian optimization. The "AI copilot" is rule-based
  and deterministic; it does not call a language model.
- Dynamic discovery of new liquid assets (fixed 10-asset universe).

## To verify next (needs network access to exchanges)

1. `GET /api/exchanges/health` returns `ok: true` for each exchange.
2. Run `tests/` plus a manual `GET /api/ohlcv?symbol=BTC/USDT&timeframe=1h` against live Binance and compare the last
   closed candle with the exchange UI.
3. Backtest each strategy on at least 2 years of real data per symbol, then `/api/validate`. Only strategies that pass
   the gate may paper trade.
4. Paper trade for several weeks before any discussion of live execution.

## Test report

`python -m pytest -q tests` → **87 passed** (2026-11-07, Python 3.13, pandas 3.1). JUnit XML: `docs/test-report.xml`.
