# Promovent audit report: V2.0 → V2.5

Audit of the repository at commit `368289a` (V2.0), the gaps found, and the state after the V2.5 work.
Classifications: **VERIFIED** (proven by a test or a run whose output is in TEST_REPORT.md),
**IMPLEMENTED** (code exists and is tested against fakes/fixtures, but not against the real external
service), **PARTIALLY IMPLEMENTED**, **BLOCKED** (cannot be completed from this environment; reason given),
**NOT IMPLEMENTED**. Generated (synthetic) data is never counted as live data.

Environment facts that limit verification (checked 2026-11-07, not assumed):
- The sandbox egress proxy refuses every exchange, exchange testnet, data provider and hosting API:
  `api.binance.com`, `testnet.binance.vision`, `api-testnet.bybit.com`, `www.okx.com`, `stream.binance.com`,
  `api.whale-alert.io`, `cryptopanic.com`, `api.telegram.org`, `api.render.com`, `backboard.railway.app`
  (proxy log: `connect_rejected`). Inside Docker containers these names do not even resolve.
- No exchange, provider, Telegram, SMTP, Render or Railway credentials exist in this session.
- A request to widen the session's network allow-list could not be shown on the user's app version.

## 1. Baseline (V2.0, commit 368289a)

| # | Area | V2.0 state | Gap |
|---|---|---|---|
| 1 | Backend architecture | FastAPI app, single process, API-key auth, roles, in-process rate limit | No worker, no shared state |
| 2 | Database | Raw SQLite (`storage.py`, one SQL migration) | No PostgreSQL, no ORM, no rollback, no backups |
| 3 | Trading execution | Paper broker only; live modes raised `LiveTradingUnavailable` on every order | **Root cause of "modes 4/5 refuse every order": there was no signed exchange client at all; the refusal was a hard-coded guard in `ExecutionAgent.execute`, by design** |
| 4 | Exchange integrations | Public REST read-only adapters (Binance, Bybit, OKX, Coinbase) | No authenticated/trading endpoints |
| 5 | Market data | REST polling of closed candles | No WebSockets, no order-book maintenance, no stale detection |
| 6 | Technical analysis | Indicators, non-repainting structure, regimes, scoring, 9 strategies, backtester | Complete for V2.0 scope |
| 7 | AI / ML | None ("copilot" is rule-based) | No ML at all |
| 8 | Frontend | One static HTML page served by FastAPI | No Next.js/TypeScript/Tailwind, one page instead of 12 |
| 9 | Notifications | Alerts stored in SQLite only | No Telegram, no email |
| 10 | Docker | Dockerfile written, never built | No compose, no Postgres/Redis/worker services |
| 11 | Deployment | None | No URL |
| 12 | Tests | 87 passing (pytest) | No DB, WebSocket, execution, frontend or Docker tests |

## 2. After V2.5

| Area | Feature | Status | Evidence / reason |
|---|---|---|---|
| Execution | Signed clients: Binance spot, Bybit v5 spot, OKX v5 spot (`execution/clients.py`) | **IMPLEMENTED** | Binance signature matches Binance's documented example; every request in the Binance fake is HMAC-verified server-side; Bybit/OKX signatures verified by fakes implementing the documented algorithms. **Not run against a real exchange or testnet: BLOCKED (network + no keys).** |
| Execution | Balance, market, limit, stop-loss, take-profit (OCO on Binance/OKX; stop on exchange + engine-watched TP on Bybit), cancel, status, open orders | **IMPLEMENTED** | `tests/test_execution.py` (26 tests) |
| Execution | Central engine: 13 named preflight checks, mode 4 confirm tokens (expiring, single use), mode 5 activation + allow-lists + per-order cap, partial fills, protective orders, emergency flatten + kill switch on protection failure, reconciliation | **VERIFIED (against fakes)** | same file; failure scenarios: invalid key, bad signature, insufficient balance, disconnect, duplicates, stale data, missing stop, daily-loss lockout, partial fill, withdrawal-enabled key |
| Execution | Zero withdrawal functionality | **VERIFIED** | Original test kept unchanged; added a test banning every documented withdrawal/transfer/deposit-address path; keys with withdrawals enabled are refused |
| Market data | WebSocket adapters Binance/Bybit/OKX: trades, klines, books, tickers, funding, open interest (Bybit/OKX; Binance OI is REST-only) | **IMPLEMENTED** | Parsers tested on documented message formats |
| Market data | Reconnect/backoff, heartbeat (protocol + app pings), stale detection, dedupe, timestamp checks, book sequencing, subscribe rate limit | **VERIFIED (local WebSocket server)** | `tests/test_market_data.py` drops connections, goes silent, refuses connections |
| Market data | Live connection to exchanges | **BLOCKED** | In Docker the worker logs `gaierror: Name or service not known` and backs off (screenshot: dashboard stream panel shows BACKOFF, no price) |
| Whale | Whale Alert + Etherscan clients, flow classification (inflow/outflow/internal/transfer; never buy/sell), clusters, unusual activity, explorer links | **IMPLEMENTED** | `tests/test_intel_notify.py`; live: **BLOCKED** (no `WHALE_ALERT_API_KEY`/`ETHERSCAN_API_KEY`, hosts blocked) |
| Whale | Blockchair large BTC/ETH transactions (no owner attribution, so always `transfer`) | **IMPLEMENTED** | fixture tests; live **BLOCKED** (host refused) |
| Whale | Blockchain.com / raw RPC providers | **NOT IMPLEMENTED** | Blockchair covers the same chains; RPC tracing needs an address-labelling source this project does not have |
| News | CryptoPanic, CoinDesk RSS, Cointelegraph RSS, Reddit OAuth, Fear & Greed; lexicon sentiment + categories with source and timestamp | **IMPLEMENTED** | tests with recorded-format fixtures; live: **BLOCKED** |
| News | Official exchange announcements: Bybit and OKX public APIs; delistings/maintenance tagged as exchange incidents | **IMPLEMENTED** | fixture tests; live **BLOCKED**. Binance: **NOT IMPLEMENTED** (no documented announcements API; no scraping) |
| Notifications | Telegram Bot API, SMTP email, templates, per-user preferences, delivery log with retries | **VERIFIED (email to a real local SMTP server)**; Telegram **IMPLEMENTED** | Telegram live **BLOCKED** (`api.telegram.org` refused, no bot token) |
| Database | PostgreSQL via SQLAlchemy 2 + Alembic, 15 tables incl. all required entities, pooling, transactions, rollback (downgrade), backup/restore script | **VERIFIED** | Real PostgreSQL 16: upgrade/downgrade/upgrade, rollback of a failed unit of work, 8 concurrent writers; Docker Postgres: migrations at head, `pg_dump`/`pg_restore` round trip |
| Database | SQLite for local development | **VERIFIED** | default for tests |
| Redis | Shared token-bucket rate limit, cache, worker locks (fail closed), heartbeats; degraded in-memory fallback | **VERIFIED** | Real Redis 7 tests; Docker drill: Redis stopped → API 200 with `degraded-memory`, recovers on restart |
| ML | Causal features, labels, purged walk-forward, LightGBM + RandomForest vs baseline, versioned registry with dataset docs, prediction with timestamp/version, PSI drift; cannot influence the risk engine | **VERIFIED (code and leakage controls)** | `tests/test_ml.py`. **No model has been trained on live data** (none reachable); models trained here use synthetic data and are labelled so. XGBoost not added (LightGBM covers gradient boosting); LSTM not justified (documented). |
| Frontend | Next.js 15 + TypeScript + Tailwind + Lightweight Charts, 12 required pages, reusable components, loading/empty/error/offline states, LIVE / SIMULATED / UNAVAILABLE badges | **VERIFIED** | typecheck, 8 vitest tests, `next build`, design-check 0 errors on all 12 pages at 390/1440 px; served in Docker |
| Docker | backend, worker, frontend images; compose with Postgres, Redis, health checks, volumes, depends_on, restart policies, log rotation, graceful shutdown | **VERIFIED** | images built and stack started here; all 7 checks in TEST_REPORT.md §3 |
| Deployment | Render blueprint `render.yaml` | **IMPLEMENTED (not applied)** | |
| Deployment | Deployed URL on Railway/Render | **BLOCKED** | Hosts refused by the egress proxy; no account credentials. No URL exists, and none is claimed. |
| Tests | 158 backend + 8 frontend tests, CI jobs with Postgres/Redis service containers, frontend and Docker build jobs | **VERIFIED locally**; CI run on `131f28f`: 9 of 10 jobs passed, `promovent-docker` failed (smoke step imported the API in production mode without keys; fixed and reproduced locally) | |

## 3. What the owner must provide to finish the blocked items

| Item | Needed |
|---|---|
| Live market data | Network access to the exchange hosts (Settings → environment allowed hosts) or any normal server |
| Testnet execution | `PROMOVENT_BINANCE_API_KEY/SECRET` from testnet.binance.vision (or Bybit testnet / OKX demo keys + passphrase) |
| Mainnet execution | Trade-only keys with **withdrawals disabled** and IP whitelist; `PROMOVENT_EXCHANGE_TESTNET=no`; mode + `PROMOVENT_ENABLE_LIVE=yes` |
| Whale / news | `WHALE_ALERT_API_KEY`, `ETHERSCAN_API_KEY` + verified watch addresses, `CRYPTOPANIC_API_KEY`, Reddit app credentials |
| Alerts | `TELEGRAM_BOT_TOKEN`; SMTP host/user/password/from |
| Deployment | A Render (or Railway) account connected to this repo; then apply `promovent/render.yaml` |
