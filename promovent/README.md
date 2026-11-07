# Promovent (Crypto Promovent AI v2.0)

Crypto market intelligence, research and **paper** trading. Python 3.12+, FastAPI, NumPy/pandas.

> This is not part of LSKhan. It lives in this repo the same way `done/` does.
> **What is real and what isn't is in [`STATUS.md`](./STATUS.md). Read it before trusting anything here.**

Capital preservation first: risk per trade 0.5 %, daily loss limit 2 %, weekly 4 %, max 3 positions,
leverage off, martingale rejected by config validation, an emergency stop, and **no withdrawal code anywhere**.
Live order execution is **not implemented**; live modes refuse every order.

## Install and run

```bash
cd promovent
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q tests                      # 87 tests

# Offline demo (labeled SYNTHETIC on every screen):
PROMOVENT_SOURCE=synthetic PROMOVENT_DEV_NO_AUTH=yes uvicorn promovent.api:app --port 8000
# open http://127.0.0.1:8000  ·  API docs at /api/docs

# Real market data (needs network access to the exchange):
cp .env.example .env   # set PROMOVENT_API_KEYS, keep DEV_NO_AUTH=no
PROMOVENT_SOURCE=live PROMOVENT_API_KEYS="<32-char key>:admin" uvicorn promovent.api:app --port 8000
```

Docker: `docker build -t promovent . && docker run -p 8000:8000 -e PROMOVENT_API_KEYS=... promovent`
(Railway/Render: use the Dockerfile; they set `$PORT`.)

## Layout

| Module | What it does |
|---|---|
| `promovent/config.py` | Execution modes 1-5, `RiskConfig` with hard rules (rejects martingale, leverage, risk > 2 %) |
| `promovent/models.py` | Symbols, timeframes, OHLCV validation (rejects bad candles, never repairs), `MarketMeta` provenance |
| `promovent/data/exchanges.py` | Binance / Bybit / OKX / Coinbase public REST adapters: candles (closed only), book, trades, funding + OI; cross-exchange price monitor (strategy H) |
| `promovent/data/synthetic.py` | Deterministic regime-switching data for tests and the labeled demo |
| `promovent/ta/indicators.py` | EMA, SMA, RSI, MACD, ATR, VWAP (session + rolling), Bollinger, ADX, volume z-score, Fibonacci, volume profile |
| `promovent/ta/structure.py` | Non-repainting swings, HH/HL/LH/LL, BOS, CHoCH, sweeps, equal highs/lows, FVG, order blocks, premium/discount (definitions in the docstring) |
| `promovent/ta/regime.py` | 8 regimes + `tradeable` flag (stands aside in high-vol and transition) |
| `promovent/ta/orderflow.py` | Book imbalance, spread, depth, visible-book slippage, CVD, aggressor ratio, large trades |
| `promovent/scoring.py` | 100-point opportunity score with the spec's weights; missing data scores 0 and is listed |
| `promovent/strategies/` | 9 backtestable engines (A, B, C, D, E, F, J, K, L) + G and I as analytics |
| `promovent/risk.py` | Risk engine with veto power: sizing, heat, correlation, lockouts, kill switch, drawdown throttle |
| `promovent/backtest.py` | Next-open fills, stop-first intrabar, gap fills, fees/spread/slippage/funding/partial fills, metrics, Monte Carlo, walk-forward, validation gate |
| `promovent/paper.py` | Paper broker and `ExecutionAgent` (mode gate → validation gate → risk decision → duplicate check → fill) |
| `promovent/service.py` | Market service, scanner, alerts, rule-based copilot |
| `promovent/api.py` | FastAPI: API-key auth, viewer/trader/admin roles, rate limits, audit log |
| `promovent/static/index.html` | Trading terminal (dashboard, chart, copilot, scanner, quant lab, risk center, positions, alerts) |
| `migrations/` | SQLite schema (audit log, paper orders/trades, alerts) |

## API (all under `/api`, `X-API-Key` header)

| Method & path | Role | Purpose |
|---|---|---|
| `GET /health` | none | liveness |
| `GET /status` | viewer | mode, source, risk limits, validated strategies |
| `GET /exchanges/health` | viewer | reachability of each exchange |
| `GET /ohlcv?symbol&timeframe&limit` | viewer | closed candles + structure breaks + provenance |
| `GET /analysis?symbol&timeframe` | viewer | copilot: bias, regime, score, supporting/conflicting evidence, entry, invalidation, timestamp |
| `GET /regime` · `GET /scan` · `GET /alerts` | viewer | regime, scanner across 10 assets, alert feed |
| `GET /strategies` | viewer | rules, stops, failure conditions per strategy |
| `POST /backtest` | viewer | metrics, equity, trades, Monte Carlo |
| `POST /validate` | admin | walk-forward + Monte Carlo + gate; passing unlocks paper trading for that strategy |
| `GET /portfolio` · `POST /paper/order` | viewer · trader | paper portfolio; place the latest signal through the risk engine |
| `POST /kill` · `POST /kill/release` · `GET /audit` | trader · admin · admin | emergency stop and audit trail |

Interactive docs: `/api/docs`.
