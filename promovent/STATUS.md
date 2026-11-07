# Promovent STATUS (v2.5, 2026-11-07)

Detailed classification: [`AUDIT_REPORT.md`](./AUDIT_REPORT.md). Actual results: [`TEST_REPORT.md`](./TEST_REPORT.md).

| Area | State |
|---|---|
| Analysis, strategies, scoring, risk, backtesting, paper trading | VERIFIED (tests) |
| Live execution engine + Binance/Bybit/OKX signed clients | IMPLEMENTED, tested against fakes; **testnet/mainnet BLOCKED** (no network, no keys) |
| WebSocket market data | VERIFIED against a local WebSocket server; **exchange connections BLOCKED** |
| Whale intelligence (Whale Alert, Etherscan, Blockchair), news, sentiment, Bybit/OKX announcements | IMPLEMENTED, fixture-tested; **live BLOCKED** (no keys, hosts blocked) |
| Email alerts | VERIFIED (real local SMTP); Telegram IMPLEMENTED, live BLOCKED |
| PostgreSQL, Alembic, Redis, backups | VERIFIED (real servers + Docker) |
| ML engine | VERIFIED code and leakage controls; no model trained on live data |
| Next.js frontend (12 pages) | VERIFIED (typecheck, tests, build, design check, running in Docker) |
| Docker build + compose stack | VERIFIED in the sandbox (all 7 checks, outage drills) |
| Deployment (Render/Railway) | **BLOCKED**: no network to the platforms, no credentials. No URL. |

Do not trade real money until: live market data is confirmed, at least one strategy passes validation on real
history, and assisted mode has run on a testnet.
