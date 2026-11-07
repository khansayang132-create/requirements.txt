# Promovent STATUS (v3.1, 2026-11-07)

Evidence: [`docs/v3.1-evidence-2026-11-07.md`](./docs/v3.1-evidence-2026-11-07.md). Earlier: AUDIT_REPORT.md, TEST_REPORT.md.

## V3.1 acceptance criteria

| # | Criterion | State |
|---|---|---|
| 1 | Binance market data works | **VERIFIED** via `data-api.binance.vision` (api.binance.com is geo-blocked here: 451) |
| 2 | WebSocket connections work | **VERIFIED** via `data-stream.binance.vision`, books synced; reconnect/stale tested locally |
| 3 | Technical analysis works | **VERIFIED** (tests + live) |
| 4 | Opportunity scanner works | **VERIFIED** on live Binance data |
| 5 | Risk Guardian works | **VERIFIED** (tests: breach protocol, authorization to resume; Docker: armed on $30) |
| 6 | Backtesting works | **VERIFIED**; 98 live-data combos tested, **0 pass validation** |
| 7 | Paper trading works | **VERIFIED** running on live Binance prices; no trades taken because nothing is validated |
| 8 | Exchange filters respected | **VERIFIED** (real Binance filters; reject, never enlarge) |
| 9 | Trading execution tested | **Against a signature-verifying fake only.** Binance testnet is geo-blocked here |
| 10 | Withdrawal functionality absent | **VERIFIED** (tests + code scan) |
| 11 | Security tests pass | **VERIFIED** (185 backend tests) |
| 12 | Docker builds | **VERIFIED** (sandbox; CI builds the real Dockerfile from scratch) |
| 13 | VPS deployment verified | **NOT DONE**: no VPS available. Guide: DEPLOY_VPS.md |
| 14 | Restart recovery tested | **VERIFIED** (`kill -9` drill in Docker; state persisted) |

**Do not trade real money.** No strategy passes validation on live data, and no real order has been tested.
