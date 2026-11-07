"""Strategy engines. Each emits causal signals decided on bar close.

A signal row at bar i has side (+1/-1), stop and target. The backtester and the
paper broker fill it at the *next* bar's open, so a strategy cannot trade on a
price it has not seen. Stops are distance-based from the close; the risk engine
re-checks them against the actual fill.
"""
from .base import Strategy
from .library import REGISTRY, get_strategy

__all__ = ["Strategy", "REGISTRY", "get_strategy"]
