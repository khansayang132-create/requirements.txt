# Live-data results, 2026-11-07 (OKX)

First run of Promovent against real exchange data. Source: OKX public REST and WebSocket, reached from the
build sandbox after a network allow-list was approved. Binance answered HTTP 451 ("restricted location") and
Bybit HTTP 403 (CloudFront country block) to this server; that is the exchanges' geo policy for the sandbox's
location, not a fault in Promovent. Coinbase was not on the allow-list.

## 1. Market data (VERIFIED live)

- REST: 3,000 closed 1h candles per symbol via `/market/candles` + paged `/market/history-candles`
  (2026-07-05 → 2026-11-07, 0 gaps), order book, trades, funding rate and open interest.
- WebSocket (45 s run, BTC and ETH): 1,220 messages, 0 reconnects, both order books in sequence (OKX
  `prevSeqId` check), funding and open interest received, 1m candles closed, 1 duplicate dropped.
  OKX's documented port 8443 is blocked by the sandbox proxy; port 443 works and is now the default
  (`PROMOVENT_OKX_WS_PORT=8443` restores it).
- Docker stack (`docker-compose.sandbox.yml`): worker streams BTC/ETH/SOL, API serves live analysis and a
  10-symbol scan with no errors; screenshots in `docs/screenshots/v2.5-docker-live-okx/`.

## 2. Strategy validation on real data: none pass

1h candles, 2026-07-05 → 2026-11-07, $10,000, 10 bps fee per side + 2 bps spread + 3 bps slippage, default
risk limits (0.5 % per trade; trading stops at 15 % drawdown). Gate: ≥ 30 trades, profit factor ≥ 1.15,
out-of-sample Sharpe ≥ 0.3, in/out-of-sample degradation ≤ 1.0, Monte Carlo 95 % drawdown better than -25 %.

| Symbol | Strategy | Trades | Net return | PF | Sharpe | Max DD | OOS Sharpe | Gate |
|---|---|---|---|---|---|---|---|---|
| BTC/USDT | trend_following | 19 | +2.13% | 1.38 | +1.15 | -3.48% | -0.34 | FAIL |
| BTC/USDT | liquidity_sweep_reversal | 75 | -14.87% | 0.41 | -5.48 | -15.20% | -7.32 | FAIL |
| BTC/USDT | breakout_retest | 106 | -13.78% | 0.52 | -5.31 | -14.91% | -9.77 | FAIL |
| BTC/USDT | vwap_mean_reversion | 10 | -1.87% | 0.58 | -1.30 | -2.56% | 0.0 | FAIL |
| BTC/USDT | momentum_continuation | 84 | -10.66% | 0.59 | -3.71 | -13.32% | -1.31 | FAIL |
| BTC/USDT | volatility_expansion | 42 | -7.96% | 0.51 | -3.53 | -7.96% | -2.31 | FAIL |
| BTC/USDT | market_structure | 94 | -11.18% | 0.62 | -3.73 | -12.74% | -8.02 | FAIL |
| ETH/USDT | trend_following | 26 | -3.29% | 0.67 | -1.71 | -4.93% | -3.01 | FAIL |
| ETH/USDT | liquidity_sweep_reversal | 48 | -15.07% | 0.20 | -6.92 | -15.07% | -10.94 | FAIL |
| ETH/USDT | breakout_retest | 94 | -7.52% | 0.75 | -2.40 | -10.76% | -2.68 | FAIL |
| ETH/USDT | vwap_mean_reversion | 10 | -3.41% | 0.30 | -2.68 | -4.08% | 0.0 | FAIL |
| ETH/USDT | momentum_continuation | 89 | -13.87% | 0.46 | -5.69 | -14.97% | -1.35 | FAIL |
| ETH/USDT | volatility_expansion | 46 | -3.98% | 0.76 | -1.49 | -5.72% | -4.27 | FAIL |
| ETH/USDT | market_structure | 85 | -10.92% | 0.51 | -4.72 | -11.99% | -4.3 | FAIL |
| SOL/USDT | trend_following | 12 | +2.32% | 1.73 | +1.59 | -1.66% | -0.02 | FAIL |
| SOL/USDT | liquidity_sweep_reversal | 75 | -15.14% | 0.45 | -4.53 | -15.14% | -11.26 | FAIL |
| SOL/USDT | breakout_retest | 106 | -11.32% | 0.64 | -3.62 | -12.23% | -8.52 | FAIL |
| SOL/USDT | vwap_mean_reversion | 11 | +1.76% | 1.47 | +0.99 | -2.39% | 0.4 | FAIL |
| SOL/USDT | momentum_continuation | 96 | -10.00% | 0.61 | -3.57 | -11.56% | 0.37 | FAIL |
| SOL/USDT | volatility_expansion | 48 | -5.48% | 0.69 | -2.17 | -8.27% | -6.85 | FAIL |
| SOL/USDT | market_structure | 98 | -14.68% | 0.43 | -6.51 | -14.82% | -8.43 | FAIL |

**Result: 0 of 21 pass.** The validation gate therefore blocks every strategy from paper and live trading.
The few positive results (trend following on BTC/SOL, VWAP mean reversion on SOL) have too few trades and
fail out of sample. Parameters were NOT tuned to make anything pass. Four months is a short sample; repeat
on longer history and other timeframes before drawing wider conclusions.

## 3. ML on real data: not useful yet

```
dataset rows 8367 positive rate {'BTC/USDT': 0.529, 'ETH/USDT': 0.552, 'SOL/USDT': 0.504}
lightgbm lig-fa9ddc489560bc23-1794039515 mean AUC 0.555 | Brier 0.2736 vs baseline 0.2478 | beats baseline: False
   fold AUCs [0.593, 0.572, 0.511, 0.546]
random_forest ran-fa9ddc489560bc23-1794039519 mean AUC 0.577 | Brier 0.2522 vs baseline 0.2478 | beats baseline: False
   fold AUCs [0.656, 0.573, 0.509, 0.57]
```

AUC slightly above 0.5 but Brier score worse than the base rate in both models: the probabilities are not
better than "always predict the average". The output stays advisory and cannot affect trades.

## 4. Not tested live

Order execution: Binance testnet is geo-blocked from this server, and no OKX demo-trading or Bybit testnet
keys exist. Execution remains verified only against fakes.
