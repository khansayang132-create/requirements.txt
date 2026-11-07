"""Database access: engine with pooling, migrations, and the Store repository.

URL from PROMOVENT_DATABASE_URL, e.g.
  postgresql+psycopg://promovent:***@postgres:5432/promovent   (production)
  sqlite:///promovent.db                                       (local dev)
Store(url) runs Alembic migrations to head on startup unless migrate=False.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import (KV, Alert, AuditLog, Base, Notification, Order, PositionRow, RiskEvent, utcnow)

ROOT = Path(__file__).resolve().parents[2]


class DatabaseUnavailable(RuntimeError):
    pass


def make_engine(url: str):
    if url.startswith("sqlite"):
        kw = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kw["poolclass"] = StaticPool
        return create_engine(url, **kw)
    return create_engine(url, pool_size=int(os.getenv("PROMOVENT_DB_POOL", "5")), max_overflow=10,
                         pool_pre_ping=True, pool_recycle=1800)


def upgrade(url: str, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, revision)


def downgrade(url: str, revision: str = "base") -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.downgrade(cfg, revision)


def _row(o) -> dict:
    d = {c.key: getattr(o, c.key) for c in o.__mapper__.column_attrs}
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    if "metadata_" in d:
        d["metadata"] = d.pop("metadata_")
    return d


class Store:
    def __init__(self, url: str | None = None, migrate: bool = True):
        url = url or os.getenv("PROMOVENT_DATABASE_URL", "sqlite://")
        if url == ":memory:":
            url = "sqlite://"
        elif "://" not in url:
            url = f"sqlite:///{url}"
        self.url = url
        self.engine = make_engine(url)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        if migrate:
            if url == "sqlite://":  # in-memory: one shared connection, create directly from models
                Base.metadata.create_all(self.engine)
            else:
                upgrade(url)

    @contextmanager
    def session(self):
        s: Session = self.Session()
        try:
            yield s
            s.commit()
        except SQLAlchemyError as e:
            s.rollback()
            raise DatabaseUnavailable(f"database error: {type(e).__name__}: {str(e).splitlines()[0][:200]}") from e
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def health(self) -> dict:
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
            return {"ok": True, "dialect": self.engine.dialect.name}
        except SQLAlchemyError as e:
            return {"ok": False, "dialect": self.engine.dialect.name, "error": str(e).splitlines()[0][:200]}

    # --- audit ---------------------------------------------------------------
    def audit(self, actor: str, action: str, detail: dict) -> None:
        with self.session() as s:
            s.add(AuditLog(actor=actor, action=action, detail=json.loads(json.dumps(detail, default=str))))

    def audit_log(self, limit: int = 100) -> list[dict]:
        with self.session() as s:
            return [_row(r) for r in s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))]

    # --- alerts --------------------------------------------------------------
    def add_alert_once(self, kind: str, symbol: str | None, message: str, window_hours: float = 6) -> bool:
        since = utcnow() - timedelta(hours=window_hours)
        with self.session() as s:
            seen = s.scalar(select(func.count()).select_from(Alert).where(
                Alert.kind == kind, Alert.symbol == symbol, Alert.message == message, Alert.ts > since))
            if seen:
                return False
            s.add(Alert(kind=kind, symbol=symbol, message=message))
            return True

    def alerts(self, limit: int = 50) -> list[dict]:
        with self.session() as s:
            return [_row(r) for r in s.scalars(select(Alert).order_by(Alert.id.desc()).limit(limit))]

    # --- orders / positions ----------------------------------------------------
    def order_exists(self, coid: str) -> bool:
        with self.session() as s:
            return s.get(Order, coid) is not None

    def save_order(self, **kw) -> None:
        with self.session() as s:
            s.merge(Order(**kw))

    def update_order(self, coid: str, **kw) -> None:
        with self.session() as s:
            o = s.get(Order, coid)
            if o is None:
                raise KeyError(coid)
            for k, v in kw.items():
                setattr(o, k, v)

    def get_order(self, coid: str) -> dict | None:
        with self.session() as s:
            o = s.get(Order, coid)
            return _row(o) if o else None

    def orders(self, venue: str | None = None, status: list[str] | None = None, limit: int = 200) -> list[dict]:
        q = select(Order).order_by(Order.ts.desc()).limit(limit)
        if venue:
            q = q.where(Order.venue == venue)
        if status:
            q = q.where(Order.status.in_(status))
        with self.session() as s:
            return [_row(r) for r in s.scalars(q)]

    def open_position(self, **kw) -> int:
        with self.session() as s:
            p = PositionRow(**kw)
            s.add(p)
            s.flush()
            return p.id

    def close_position(self, entry_order_id: str, exit: float, reason: str, pnl: float, fees: float) -> None:
        with self.session() as s:
            p = s.scalar(select(PositionRow).where(PositionRow.entry_order_id == entry_order_id, PositionRow.closed_at.is_(None)))
            if p is None:
                raise KeyError(entry_order_id)
            p.closed_at, p.exit, p.exit_reason, p.pnl, p.fees = utcnow(), exit, reason, pnl, fees

    def positions(self, venue: str, closed: bool = False, limit: int = 100) -> list[dict]:
        q = select(PositionRow).where(PositionRow.venue == venue)
        q = q.where(PositionRow.closed_at.is_not(None) if closed else PositionRow.closed_at.is_(None))
        with self.session() as s:
            return [_row(r) for r in s.scalars(q.order_by(PositionRow.id.desc()).limit(limit))]

    # --- risk events / notifications ------------------------------------------
    def risk_event(self, kind: str, severity: str, detail: dict) -> None:
        with self.session() as s:
            s.add(RiskEvent(kind=kind, severity=severity, detail=json.loads(json.dumps(detail, default=str))))

    def risk_events(self, limit: int = 100) -> list[dict]:
        with self.session() as s:
            return [_row(r) for r in s.scalars(select(RiskEvent).order_by(RiskEvent.id.desc()).limit(limit))]

    def add_notification(self, **kw) -> int:
        with self.session() as s:
            n = Notification(**kw)
            s.add(n)
            s.flush()
            return n.id

    def notifications(self, limit: int = 100) -> list[dict]:
        with self.session() as s:
            return [_row(r) for r in s.scalars(select(Notification).order_by(Notification.id.desc()).limit(limit))]

    # --- persistent operating state ----------------------------------------------
    def kv_get(self, key: str, default=None):
        with self.session() as s:
            row = s.get(KV, key)
            return row.value if row is not None else default

    def kv_set(self, key: str, value) -> None:
        with self.session() as s:
            row = s.get(KV, key)
            v = json.loads(json.dumps(value, default=str))
            if row is None:
                s.add(KV(key=key, value=v))
            else:
                row.value = v

    def add(self, obj) -> None:
        with self.session() as s:
            s.add(obj)

    def list(self, model, limit: int = 100, order=None) -> list[dict]:
        with self.session() as s:
            q = select(model).limit(limit)
            if order is not None:
                q = q.order_by(order)
            return [_row(r) for r in s.scalars(q)]


__all__ = ["Store", "DatabaseUnavailable", "upgrade", "downgrade", "make_engine", "utcnow", "timezone"]
