"""Real-time market data over WebSockets (Binance, Bybit, OKX).

events.py           normalized MarketEvent
exchange_adapters/  per-exchange URLs, subscription messages, pings and parsers
websocket_manager   one connection: reconnect with backoff, heartbeat, stale detection, send rate limit
data_validator      timestamp sanity, duplicate suppression, per-stream ordering
orderbook           local L2 book with snapshot + delta sequencing (gap => resync)
candle_processor    forming/closed candles from kline events or from trades
market_stream       wires it together and keeps a status/last-price snapshot
"""
