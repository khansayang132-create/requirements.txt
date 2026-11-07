"""SQLAlchemy models. PostgreSQL in production, SQLite for local development and tests.

Exchange API secrets are NOT stored in the database: they come from environment
variables (or the platform's secret store) at runtime. `exchange_accounts` keeps
only non-secret metadata: label, key fingerprint, last permission check.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16))  # viewer | trader | admin
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True)  # sha256 of the API key, never the key
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(254))
    alert_prefs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class ExchangeAccount(Base):
    __tablename__ = "exchange_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(64))
    testnet: Mapped[bool] = mapped_column(Boolean, default=True)
    key_fingerprint: Mapped[str | None] = mapped_column(String(16))  # first 16 hex of sha256(key)
    can_trade: Mapped[bool | None] = mapped_column(Boolean)
    withdrawals_enabled: Mapped[bool | None] = mapped_column(Boolean)
    last_checked_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("exchange", "label"),)


class MarketCandle(Base):
    __tablename__ = "market_candles"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    exchange: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(24))
    timeframe: Mapped[str] = mapped_column(String(4))
    open_time: Mapped[datetime] = mapped_column(TS)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(12))  # live | synthetic
    __table_args__ = (UniqueConstraint("exchange", "symbol", "timeframe", "open_time"),)


class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    validated_at: Mapped[datetime | None] = mapped_column(TS)
    validation: Mapped[dict | None] = mapped_column(JSON)


class SignalRow(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    strategy: Mapped[str] = mapped_column(String(64))
    exchange: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(24))
    timeframe: Mapped[str] = mapped_column(String(4))
    side: Mapped[int] = mapped_column(Integer)
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    bar_time: Mapped[datetime] = mapped_column(TS)
    source: Mapped[str] = mapped_column(String(12))


class Order(Base):
    """Every order sent (or refused) for paper or live venues."""
    __tablename__ = "orders"
    client_order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    venue: Mapped[str] = mapped_column(String(16))     # paper | binance | bybit | okx
    testnet: Mapped[bool] = mapped_column(Boolean, default=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64))
    parent_id: Mapped[str | None] = mapped_column(String(40))  # protective orders point at the entry
    role: Mapped[str] = mapped_column(String(16), default="entry")  # entry | stop | take_profit | oco | exit
    symbol: Mapped[str] = mapped_column(String(24))
    side: Mapped[int] = mapped_column(Integer)
    order_type: Mapped[str] = mapped_column(String(24))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float)
    stop: Mapped[float | None] = mapped_column(Float)
    target: Mapped[float | None] = mapped_column(Float)
    strategy: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20))
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_price: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_orders_venue_status", "venue", "status"),)


class Execution(Base):
    __tablename__ = "executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(ForeignKey("orders.client_order_id"))
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    trade_id: Mapped[str | None] = mapped_column(String(64))


class PositionRow(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    venue: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(24))
    side: Mapped[int] = mapped_column(Integer)
    qty: Mapped[float] = mapped_column(Float)
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    strategy: Mapped[str] = mapped_column(String(64), default="")
    entry_order_id: Mapped[str] = mapped_column(String(40))
    opened_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(TS)
    exit: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String(24))
    pnl: Mapped[float | None] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0.0)


class BacktestResult(Base):
    __tablename__ = "backtest_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    strategy: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(24))
    timeframe: Mapped[str] = mapped_column(String(4))
    source: Mapped[str] = mapped_column(String(12))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    venue: Mapped[str] = mapped_column(String(16))
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    heat: Mapped[float] = mapped_column(Float)
    drawdown: Mapped[float] = mapped_column(Float)
    positions: Mapped[list] = mapped_column(JSON, default=list)


class RiskEvent(Base):
    __tablename__ = "risk_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))  # info | warn | critical
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str | None] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_alerts_dedupe", "kind", "symbol", "ts"),)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(16))  # telegram | email | dashboard
    event: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))   # sent | failed | skipped
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class MLModel(Base):
    __tablename__ = "ml_models"
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))
    data_source: Mapped[str] = mapped_column(String(12))
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
