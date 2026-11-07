# Promovent (Crypto Promovent AI v2.5)

Crypto market intelligence, research, paper trading and risk-gated live execution.
Backend: Python 3.12, FastAPI, SQLAlchemy/Alembic on PostgreSQL, Redis, a background worker.
Frontend: Next.js 15, TypeScript, Tailwind, TradingView Lightweight Charts.

> Not part of LSKhan; it lives in this repo like `done/`.
> **What is proven and what is not:** [`AUDIT_REPORT.md`](./AUDIT_REPORT.md) and [`TEST_REPORT.md`](./TEST_REPORT.md).
> Short version: everything below is built and tested, but it has **never connected to a real exchange,
> data provider or hosting platform** (the build sandbox blocks them), and **it is not deployed**.

Capital preservation first: 0.5 % risk per trade, 2 % daily / 4 % weekly loss limits, max 3 positions, leverage
off, martingale rejected, emergency stop. **There is no withdrawal code**, and keys that allow withdrawals are refused.

## Architecture

```
 browser ──► Next.js (web/, :3000) ──/api/* rewrite──► FastAPI (promovent/api.py, :8000) ──► PostgreSQL
                                                          │   ▲                                 ▲
                                                          ▼   │ snapshots, locks, rate limits   │
                                                         Redis ◄──────── worker (promovent/worker.py)
                                                                          ├─ WebSocket streams (market_data/)
                                                                          ├─ scans → alerts → Telegram/email
                                                                          ├─ live order reconciliation
                                                                          └─ portfolio snapshots
 Live orders: API → LiveExecutionEngine (execution/engine.py, 13 preflight checks) → signed client (execution/clients.py) → exchange
```

| Package | Purpose |
|---|---|
| `promovent/ta/`, `strategies/`, `scoring.py`, `backtest.py`, `risk.py` | analysis, 9 strategies, scoring, backtester, risk engine (V2.0, unchanged in behaviour) |
| `promovent/execution/` | signed Binance/Bybit/OKX spot clients and the live execution engine (modes 4 and 5) |
| `promovent/market_data/` | WebSocket adapters, connection manager, validator, order books, candles, stream |
| `promovent/intel/` | whale intelligence (Whale Alert, Etherscan), news and sentiment (CryptoPanic, RSS, Reddit, Fear & Greed) |
| `promovent/notify.py` | Telegram and SMTP email with per-user preferences and delivery log |
| `promovent/db/` + `alembic/` | SQLAlchemy models (15 tables) and migrations |
| `promovent/cache.py` | Redis rate limiting, cache, locks, heartbeats (degrades to memory) |
| `promovent/ml/` | features, dataset, LightGBM/RandomForest training, registry, prediction, drift |
| `promovent/worker.py` | background jobs |
| `web/` | Next.js app: dashboard, markets, scanner, trading, portfolio, strategies, backtesting, whale-intelligence, news, analytics, risk-center, settings |

## Run it

### Full stack with Docker (recommended)

```bash
cd promovent
cp .env.example .env
#   set POSTGRES_PASSWORD and PROMOVENT_API_KEYS (python -c "import secrets;print(secrets.token_urlsafe(32))")
docker compose up -d --build
docker compose ps                  # all five services should become "healthy"
curl http://127.0.0.1:8000/api/health
open http://127.0.0.1:3000         # Settings → paste your API key
```

Database: `scripts/db.sh backup|restore <file>|migrate|rollback <rev>`. Migrations also run on every backend start.

### Local development

```bash
cd promovent
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
python -m pytest -q tests                      # set PROMOVENT_TEST_DATABASE_URL / _REDIS_URL to include Postgres/Redis tests
PROMOVENT_ENV=development PROMOVENT_SOURCE=synthetic PROMOVENT_DEV_NO_AUTH=yes uvicorn promovent.api:app --port 8000
cd web && npm ci && npm run dev                 # http://127.0.0.1:3000 (proxies /api to :8000)
```

`PROMOVENT_SOURCE=synthetic` is a labelled demo mode (SIMULATED banner everywhere). `PROMOVENT_ENV=production`
refuses to start with synthetic data or with auth disabled.

## Turning on live trading (in this order)

1. Paper trade first. Validate a strategy (`/strategies` → Validate, admin key). Only validated strategies can trade.
2. Create a **trade-only** key on the exchange: spot trading on, **withdrawals off**, IP whitelist on.
3. Testnet first: `PROMOVENT_LIVE_EXCHANGE=binance`, `PROMOVENT_EXCHANGE_TESTNET=yes`, keys from testnet.binance.vision.
4. `PROMOVENT_MODE=assisted_live` and `PROMOVENT_ENABLE_LIVE=yes`. `/trading` → Live preflight shows every check;
   Propose → Confirm sends one order and places its stop/take-profit.
5. Mode 5 (`autonomous_live`) additionally needs an admin to POST `/api/live/autonomy` with allowed symbols,
   strategies, a per-order notional cap, and `confirm_phrase: "I ACCEPT AUTONOMOUS LIVE TRADING"`.

v2.5 trades **spot, long only**. Short signals are refused rather than sent to a margin account.

## API

Interactive docs at `/api/docs`. Header `X-API-Key`; roles viewer < trader < admin.

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /api/health` | none | DB, Redis, worker heartbeats, notification channels (503 if DB down) |
| `GET /api/status`, `/api/ohlcv`, `/api/analysis`, `/api/regime`, `/api/scan`, `/api/alerts`, `/api/strategies` | viewer | market and analysis data, every payload with exchange/symbol/timestamp/source |
| `GET /api/stream` | viewer | WebSocket snapshot from the worker (price, timestamp, connection state) |
| `POST /api/backtest` · `POST /api/validate` | viewer · admin | research; validation persists in `strategies` |
| `GET /api/portfolio` · `POST /api/paper/order` | viewer · trader | paper trading |
| `GET /api/live/status` · `POST /api/live/preflight` · `POST /api/live/propose` · `POST /api/live/confirm` | viewer · trader | live execution (mode 4) |
| `POST /api/live/autonomy` · `POST /api/live/reconcile` · `GET /api/live/orders` | admin · admin · viewer | mode 5 activation, reconciliation, live order log |
| `GET /api/whales`, `GET /api/news` | viewer | on-chain flows, news and sentiment (errors listed per provider) |
| `GET /api/ml/models`, `POST /api/ml/train`, `GET /api/ml/predict` | viewer · admin · viewer | ML registry, training, prediction with drift |
| `GET/PUT /api/settings/alerts`, `POST /api/settings/alerts/test`, `GET /api/notifications` | viewer | alert preferences and delivery log |
| `GET /api/risk/events`, `POST /api/kill`, `POST /api/kill/release`, `GET /api/audit` | viewer · trader · admin · admin | risk |

## Deploy

`render.yaml` is a Render Blueprint (Postgres, Key Value/Redis, backend, worker, frontend). In Render: New →
Blueprint → this repo → path `promovent/render.yaml`, then enter the `sync: false` secrets. Set
`PROMOVENT_BACKEND_URL` on the frontend to the backend's URL **before** its first build (Next.js rewrites are fixed at
build time). Not yet applied: see TEST_REPORT.md §4.
