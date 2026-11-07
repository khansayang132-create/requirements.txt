"""Promovent: crypto market intelligence, research, paper and live trading.

Capital preservation first. No withdrawals (no code path exists), leverage off by default,
martingale rejected by config validation. Live execution requires an explicit live mode,
PROMOVENT_ENABLE_LIVE=yes, a trade-only API key and the preflight checks in execution/engine.py.
"""
__version__ = "2.5.0"
