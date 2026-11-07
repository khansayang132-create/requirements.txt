"""Order-flow analytics from an order-book snapshot and a recent-trades list.

Visible depth is not executable liquidity: books are spoofed, refreshed and
pulled. `slippage_estimate` walks the *visible* book only and says so.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Book:
    bids: list[tuple[float, float]]  # (price, size), best first
    asks: list[tuple[float, float]]

    def validate(self) -> "Book":
        if not self.bids or not self.asks:
            raise ValueError("empty book side")
        if any(p <= 0 or q < 0 for p, q in self.bids + self.asks):
            raise ValueError("non-positive price or negative size")
        if self.bids[0][0] >= self.asks[0][0]:
            raise ValueError("crossed book")
        bp = [p for p, _ in self.bids]
        ap = [p for p, _ in self.asks]
        if bp != sorted(bp, reverse=True) or ap != sorted(ap):
            raise ValueError("book levels not sorted")
        return self


def book_metrics(book: Book, depth_pct: float = 0.005) -> dict:
    book.validate()
    bb, ba = book.bids[0][0], book.asks[0][0]
    mid = (bb + ba) / 2
    bid_depth = sum(p * q for p, q in book.bids if p >= mid * (1 - depth_pct))
    ask_depth = sum(p * q for p, q in book.asks if p <= mid * (1 + depth_pct))
    tot = bid_depth + ask_depth
    return {"mid": mid, "spread": ba - bb, "spread_bps": (ba - bb) / mid * 1e4,
            "bid_depth_quote": bid_depth, "ask_depth_quote": ask_depth,
            "imbalance": (bid_depth - ask_depth) / tot if tot else 0.0,
            "depth_window_pct": depth_pct, "note": "visible liquidity only; not guaranteed executable"}


def slippage_estimate(book: Book, side: int, qty: float) -> dict:
    """Average fill vs mid for a market order of `qty` base units, walking visible levels."""
    book.validate()
    levels = book.asks if side > 0 else book.bids
    mid = (book.bids[0][0] + book.asks[0][0]) / 2
    remaining, cost = qty, 0.0
    for p, q in levels:
        take = min(q, remaining)
        cost += take * p
        remaining -= take
        if remaining <= 1e-15:
            break
    filled = qty - max(remaining, 0)
    if filled <= 0:
        return {"filled": 0.0, "complete": False}
    avg = cost / filled
    return {"filled": filled, "complete": remaining <= 1e-15, "avg_price": avg,
            "slippage_bps": (avg - mid) / mid * 1e4 * side}


def trade_flow(trades: list[dict], large_quote: float = 100_000) -> dict:
    """trades: [{price, qty, is_buyer_maker, ts}] (buyer-maker => aggressor sold)."""
    if not trades:
        return {"available": False}
    signed = np.array([t["qty"] * (-1 if t["is_buyer_maker"] else 1) for t in trades], float)
    quote = np.array([t["qty"] * t["price"] for t in trades], float)
    buy_q = quote[signed > 0].sum()
    sell_q = quote[signed < 0].sum()
    large = [t for t, qv in zip(trades, quote, strict=True) if qv >= large_quote]
    return {"available": True, "n": len(trades), "cvd_base": float(signed.sum()),
            "aggressive_buy_quote": float(buy_q), "aggressive_sell_quote": float(sell_q),
            "aggressor_ratio": float(buy_q / (buy_q + sell_q)) if buy_q + sell_q else 0.5,
            "large_trades": len(large), "large_trade_threshold_quote": large_quote}
