# Promovent V2.5 test report

Run on 2026-11-07 in the Claude Code cloud sandbox (Linux, Python 3.13 for local runs, Python 3.12 in the
Docker image, Node 22). Every number below is copied from actual command output. Nothing here was run
against a real exchange, testnet, data provider, Telegram or a hosting platform: the sandbox blocks them
(see AUDIT_REPORT.md). Where a test uses a fake, the fake is named.

## 1. Backend (pytest)

Command: `python -m pytest tests -rs` with `PROMOVENT_TEST_DATABASE_URL` (local PostgreSQL 16.x) and
`PROMOVENT_TEST_REDIS_URL` (local Redis) set. Result: **158 passed, 0 failed, 0 skipped** (19.2 s).
JUnit XML: `docs/test-report.xml`. Lint: `ruff check .` → All checks passed. Shell: `shellcheck -S warning` → clean.

| File | Tests | Seconds | Covers |
|---|---|---|---|
| `test_api.py` | 8 | 2.23 | auth, roles, input validation, backtest/validate, kill switch, rate limit |
| `test_backtest.py` | 11 | 0.29 | next-open fills, stop-first, gaps, costs, partial fills, funding, walk-forward, gate |
| `test_exchanges.py` | 11 | 0.02 | REST parsers (documented formats), HTTP failure handling, validation |
| `test_execution.py` | 26 | 0.15 | signing (Binance official vector), signed clients vs fakes, engine preflight, modes 4/5, failure scenarios |
| `test_indicators.py` | 6 | 0.01 | indicator math |
| `test_integration_pg_redis.py` | 3 | 0.62 | **real PostgreSQL**: migrate down/up, transaction rollback, pooled concurrent writes; **real Redis**: shared rate limit, locks, cache, heartbeats |
| `test_intel_notify.py` | 14 | 0.08 | Whale Alert/Etherscan/Blockchair/CryptoPanic/RSS/Reddit/Fear&Greed/Bybit+OKX announcements parsing and errors; **email delivered to a real local SMTP server**; Telegram via fake |
| `test_market_data.py` | 10 | 3.57 | **real local WebSocket server**: reconnect after drop, stale-feed detection, unreachable host backoff, Bybit app ping; validator, books, candles, parsers |
| `test_ml.py` | 7 | 2.88 | causal features, label horizon, purged splits, LightGBM + RF train/version/predict/drift, ML isolated from risk |
| `test_no_lookahead.py` | 17 | 0.56 | no repaint / no look-ahead in structure, regime and all 9 strategies |
| `test_paper.py` | 7 | 0.09 | paper execution gate, duplicates, stops, kill switch, partial fill, migrations idempotent |
| `test_risk.py` | 19 | 0.00 | sizing, limits, lockouts, correlation, heat, hard config rules, live switch |
| `test_security.py` | 4 | 0.02 | **withdrawal prohibition (original test, unchanged)**, withdrawal/transfer endpoint ban, signing confined to `execution/`, no hard-coded secrets |
| `test_structure.py` | 5 | 0.01 | swings, BOS, CHoCH, FVG, sweeps |
| `test_v25_api.py` | 10 | 7.12 | production guard, health, live status names missing keys, autonomy activation, alert settings, validation persistence, **DB outage → 503**, **Redis outage → degraded**, worker start/stop on SIGTERM (subprocess) |

### Required failure scenarios

| Scenario | Test | Result |
|---|---|---|
| Invalid API keys | `test_invalid_api_key_reported`, `test_bad_secret_signature_rejected` | pass: AuthError with exchange code; preflight `connection` fails with the reason |
| Insufficient balance | `test_insufficient_balance_preflight_and_exchange`, Bybit/OKX flow tests | pass: preflight `balance` fails; exchange error mapped to InsufficientBalance |
| Exchange disconnection | `test_exchange_disconnect_reported`; WS `test_unreachable_server_backs_off_without_crashing` | pass |
| Duplicate orders | `test_duplicate_order_blocked_locally_and_on_exchange`, paper `test_fill_duplicate_and_stop_close` | pass |
| Stale market data | `test_stale_data_missing_stop_short_and_unvalidated`, `test_stale_feed_detected_and_reconnected` | pass |
| Missing stop-loss | same as above (`stop_loss` check) | pass |
| Daily loss limit | `test_daily_loss_limit_blocks_live`, `test_daily_loss_lockout` | pass |
| Partial execution | `test_partial_fill_protects_filled_and_cancels_rest` | pass |
| Database outage | `test_database_outage_returns_503` + Docker drill (§3) | pass |
| Redis outage | `test_redis_outage_degrades_rate_limit_and_locks` + Docker drill (§3) | pass |

### Live exchange execution testing

**NOT RUN.** Binance spot testnet, Bybit testnet and OKX demo trading are all unreachable from this sandbox
(`testnet.binance.vision`, `api-testnet.bybit.com`, `www.okx.com`: proxy `connect_rejected`) and no testnet keys
were provided. The execution tests use in-process fakes; passing them does not prove an exchange accepted an order.

## 2. Frontend (Next.js)

| Check | Command | Result |
|---|---|---|
| Typecheck | `npm run typecheck` | pass |
| Unit tests | `npm test` (vitest) | **8 passed** (2 files): formatting, API client offline/auth/unavailable mapping, error text, API-key header, LIVE/SIMULATED/UNAVAILABLE badges, loading/error/offline/empty/stale states |
| Build | `next build` | pass, 12 pages + `/` redirect, ~102 kB shared JS |
| Design check | `.claude/skills/design-check/scripts/check.mjs` on all 12 pages, 390 and 1440 px, dark | **0 errors** on every page. 12 warnings on `/settings`: the alert checkboxes are 24 px (target 44 px); each sits inside a 44×44 px label, so the tap area meets the target. Fixed along the way: 20 px checkboxes (error), header stretching on short pages (seen in screenshots). |

## 3. Docker (actual build and run in this sandbox)

Images built: `promovent-backend:2.5` (802 MB on disk), `promovent-frontend:2.5` (346 MB on disk). Sandbox-only build
flags: `--network host --secret id=extra_ca,src=/root/.ccr/ca-bundle.crt` (the sandbox intercepts TLS; the secret is
optional and never stored in the image). `docker compose up -d --no-build` with `PROMOVENT_ENV=production`,
`PROMOVENT_SOURCE=live`, generated API key and Postgres password.

| # | Requirement | Result (output) |
|---|---|---|
| 1 | Frontend responds | `GET :3000/dashboard -> 200`; `GET :3000/api/status` through the Next.js rewrite → 200 |
| 2 | Backend health responds | `{"ok": true, "version": "2.5.0", "env": "production", "database": {"ok": true, "dialect": "postgresql"}, "redis": {"ok": true, "mode": "redis"}, ...}` |
| 3 | PostgreSQL accepts connections | `connected; public tables = 16` |
| 4 | Redis accepts connections | `PONG`; keys present: `pv:rl:*`, `pv:hb:worker-*`, `pv:c:stream_snapshot` |
| 5 | Background worker starts | container healthy (heartbeat in Redis); logs JSON lines; stream task running |
| 6 | Exchange adapters initialize | initialize and report: `binance: ConnectError: [Errno -2] Name or service not known` (same for bybit/okx/coinbase); WebSocket in BACKOFF with growing delay; no prices shown. **Initialization verified, connectivity BLOCKED.** |
| 7 | Database migrations succeed | `alembic_version = 0001` (head), run by the backend entrypoint on start |

Drills on the running stack:

| Drill | Result |
|---|---|
| `docker compose stop redis` | `/api/health` 200 with `redis: degraded-memory`; authenticated API 200; after `start`: `redis` mode again |
| `docker compose stop postgres` | `/api/health` 503; `/api/alerts` 503 `{"error":"database unavailable",...}`; recovers to 200 after `start` |
| Graceful shutdown | worker stopped in 0.5 s (exit 0, logs `stopping` → `stopped`); backend stopped in 0.9 s (exit 0, `Shutting down` → `Finished server process`) |
| Backup / restore | `scripts/db.sh backup` → 37 KB custom-format dump (verified readable); row deleted; `scripts/db.sh restore` → row back |
| Restarts | 0 restarts on backend, worker and frontend across the run |

## 4. Deployment

**BLOCKED.** `api.render.com` and `backboard.railway.app` are refused by the sandbox proxy and there are no account
credentials. No deployed URL exists. `render.yaml` is ready to apply. No production screenshots exist; the
screenshots in `docs/screenshots/` are labelled by where they came from (see `docs/screenshots/README.md`).

## 5. CI (GitHub Actions)

Run 195 on commit `131f28f`: 9 of 10 jobs passed (including `promovent` with Postgres/Redis service containers and
`promovent-web`). `promovent-docker` failed: its smoke step imported the API inside the production image without
API keys, and the production guard refused to start, as designed. Fixed by importing with `PROMOVENT_NO_AUTOAPP=1`
and adding a real start-up check (container migrates SQLite and answers `/api/health`); both steps reproduced
locally and passed before pushing.
