"""Configuration: execution modes and risk limits.

Risk limits are validated on construction. Values that break the hard rules
(leverage above the allowed cap, risk per trade above HARD_MAX_RISK_PER_TRADE,
martingale sizing) are rejected, not clamped, so a bad config fails loudly.
"""
from __future__ import annotations

import os
from enum import Enum

from pydantic import BaseModel, Field, model_validator

HARD_MAX_RISK_PER_TRADE = 0.02  # 2 %: no config may exceed this


class Mode(str, Enum):
    OBSERVATION = "observation"        # analysis only
    SIGNAL = "signal"                  # generate opportunities, no orders
    PAPER = "paper"                    # simulated fills on market data
    ASSISTED_LIVE = "assisted_live"    # every order needs user confirmation
    AUTONOMOUS_LIVE = "autonomous_live"  # orders inside configured limits

    @property
    def is_live(self) -> bool:
        return self in (Mode.ASSISTED_LIVE, Mode.AUTONOMOUS_LIVE)

    @property
    def may_place_orders(self) -> bool:
        return self in (Mode.PAPER, Mode.ASSISTED_LIVE, Mode.AUTONOMOUS_LIVE)


class RiskConfig(BaseModel):
    risk_per_trade: float = Field(0.005, gt=0)
    daily_loss_limit: float = Field(0.02, gt=0, le=0.5)
    weekly_loss_limit: float = Field(0.04, gt=0, le=0.5)
    max_drawdown: float = Field(0.15, gt=0, le=0.9)
    max_concurrent_positions: int = Field(3, ge=1, le=50)
    max_portfolio_heat: float = Field(0.015, gt=0, le=0.2)  # sum of open risk / equity
    min_reward_risk: float = Field(1.5, gt=0)
    max_correlation: float = Field(0.8, gt=0, le=1)
    max_position_notional_pct: float = Field(1.0, gt=0, le=1.0)  # 1.0 = no leverage
    leverage: float = Field(1.0, ge=1.0)
    allow_leverage: bool = False
    martingale: bool = False

    @model_validator(mode="after")
    def _hard_rules(self) -> "RiskConfig":
        if self.risk_per_trade > HARD_MAX_RISK_PER_TRADE:
            raise ValueError(f"risk_per_trade {self.risk_per_trade} exceeds hard cap {HARD_MAX_RISK_PER_TRADE}")
        if self.martingale:
            raise ValueError("martingale sizing is prohibited")
        if self.leverage > 1.0 and not self.allow_leverage:
            raise ValueError("leverage is OFF; set allow_leverage explicitly to change it")
        if self.weekly_loss_limit < self.daily_loss_limit:
            raise ValueError("weekly_loss_limit must be >= daily_loss_limit")
        return self


class Settings(BaseModel):
    mode: Mode = Mode.OBSERVATION
    risk: RiskConfig = RiskConfig()
    live_trading_enabled: bool = False  # second, explicit switch for live modes

    @model_validator(mode="after")
    def _live_gate(self) -> "Settings":
        if self.mode.is_live and not self.live_trading_enabled:
            raise ValueError("live modes require live_trading_enabled=True (PROMOVENT_ENABLE_LIVE=yes)")
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        mode = Mode(os.getenv("PROMOVENT_MODE", Mode.OBSERVATION.value))
        live = os.getenv("PROMOVENT_ENABLE_LIVE", "").lower() == "yes"
        risk = RiskConfig(risk_per_trade=float(os.getenv("PROMOVENT_RISK_PER_TRADE", "0.005")))
        return cls(mode=mode, risk=risk, live_trading_enabled=live)
