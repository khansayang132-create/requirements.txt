"""FastAPI service. Run: uvicorn promovent.api:app --host 127.0.0.1 --port 8000

Auth: header `X-API-Key`. Keys and roles come from PROMOVENT_API_KEYS
("key1:admin,key2:trader,key3:viewer"); keys are compared in constant time and
never logged. Roles: viewer (read) < trader (paper orders, engage kill switch)
< admin (validate strategies, audit log). PROMOVENT_DEV_NO_AUTH=yes disables
auth for local development only; /api/status reports it.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
import threading
import time
from typing import Literal

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .backtest import Costs, ValidationGate, monte_carlo, run, walk_forward
from .config import Mode, Settings
from .data.exchanges import ADAPTERS, get_adapter
from .models import DataValidationError, Signal, TIMEFRAMES, validate_symbol
from .paper import ExecutionAgent, OrderRejected, PaperBroker
from .risk import RiskEngine
from .service import DataUnavailable, MarketService, alerts_from_scan
from .cache import Coord
from .db import DatabaseUnavailable, Store
from .db.models import BacktestResult, Strategy as StrategyRow, User
from .execution.clients import ExecError, client_from_env
from .execution.engine import Autonomy, LiveExecutionEngine, LiveOrderRejected
from .notify import EVENTS, Notifier
from .strategies import REGISTRY, get_strategy
from .ta.regime import classify
from .ta.structure import analyze

ROLES = {"viewer": 0, "trader": 1, "admin": 2}


def _parse_keys(raw: str) -> dict[str, str]:
    out = {}
    for part in filter(None, (p.strip() for p in raw.split(","))):
        key, _, role = part.rpartition(":")
        if not key or role not in ROLES or len(key) < 24:
            raise ValueError("PROMOVENT_API_KEYS entries must be '<key of 24+ chars>:<viewer|trader|admin>'")
        out[key] = role
    return out


class RateLimiter:
    def __init__(self, rate: float = 5.0, burst: int = 30):
        self.rate, self.burst, self.b, self.lock = rate, burst, {}, threading.Lock()

    def allow(self, who: str) -> bool:
        now = time.monotonic()
        with self.lock:
            tokens, last = self.b.get(who, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                self.b[who] = (tokens, now)
                return False
            self.b[who] = (tokens - 1, now)
            return True


class SharedLimiter:
    """Token bucket in Redis (shared by all API replicas); in-process fallback when Redis is down."""
    def __init__(self, coord: Coord, rate: float = 5.0, burst: int = 30):
        self.coord, self.rate, self.burst = coord, rate, burst

    def allow(self, who: str) -> bool:
        return self.coord.allow(who, self.rate, self.burst)


class App:
    def __init__(self, settings: Settings | None = None, source: str | None = None, db: str | None = None,
                 keys: dict[str, str] | None = None, no_auth: bool | None = None, redis_url: str | None = None):
        self.env = os.getenv("PROMOVENT_ENV", "development")
        self.settings = settings or (Settings.from_env() if os.getenv("PROMOVENT_MODE") else Settings(mode=Mode.PAPER))
        self.source = source or os.getenv("PROMOVENT_SOURCE", "live")
        self.keys = keys if keys is not None else _parse_keys(os.getenv("PROMOVENT_API_KEYS", ""))
        self.no_auth = no_auth if no_auth is not None else os.getenv("PROMOVENT_DEV_NO_AUTH", "") == "yes"
        if self.env == "production":
            if self.source != "live":
                raise RuntimeError("PROMOVENT_ENV=production refuses PROMOVENT_SOURCE other than 'live' (no generated data)")
            if self.no_auth or not self.keys:
                raise RuntimeError("PROMOVENT_ENV=production requires PROMOVENT_API_KEYS and DEV_NO_AUTH off")
        self.market = MarketService(source=self.source, exchange=os.getenv("PROMOVENT_EXCHANGE", "binance"))
        self.store = Store(db or os.getenv("PROMOVENT_DATABASE_URL") or os.getenv("PROMOVENT_DB", ":memory:"))
        self.coord = Coord(redis_url if redis_url is not None else os.getenv("PROMOVENT_REDIS_URL", ""))
        self.risk = RiskEngine(self.settings.risk)
        self.broker = PaperBroker(self.store)
        try:
            validated = {r["name"] for r in self.store.list(StrategyRow, 500) if r["validated"]}
        except Exception:
            validated = set()
        self.agent = ExecutionAgent(self.settings, self.risk, self.broker, self.store, validated)
        self.limiter = SharedLimiter(self.coord)
        self.notifier = Notifier(self.store)
        self.autonomy = Autonomy()
        self._live: LiveExecutionEngine | None = None
        self.live_error: str | None = None

    def live(self) -> LiveExecutionEngine:
        """Built on first use from PROMOVENT_LIVE_EXCHANGE and that exchange's credentials."""
        if self._live is None:
            ex = os.getenv("PROMOVENT_LIVE_EXCHANGE", "binance")
            try:
                client = client_from_env(ex)
            except ExecError as e:
                self.live_error = str(e)
                raise
            self._live = LiveExecutionEngine(self.settings, self.risk, self.store, client, self.agent.validated,
                                             self.broker.state, self.autonomy)
            self.live_error = None
        return self._live


class BacktestReq(BaseModel):
    strategy: str
    symbol: str = "BTC/USDT"
    timeframe: Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"] = "1h"
    bars: int = Field(1000, ge=300, le=5000)
    params: dict[str, float] = Field(default_factory=dict)
    fee_bps: float = Field(10, ge=0, le=100)
    slippage_bps: float = Field(3, ge=0, le=200)
    spread_bps: float = Field(2, ge=0, le=200)
    funding_rate_8h: float = Field(0, ge=-0.01, le=0.01)
    initial: float = Field(10_000, gt=0, le=1e9)


class OrderReq(BaseModel):
    strategy: str
    symbol: str
    timeframe: Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"] = "1h"


class KillReq(BaseModel):
    reason: str = Field("manual", max_length=200)


class ConfirmReq(BaseModel):
    token: str = Field(min_length=10, max_length=64)
    symbol: str


class AutonomyReq(Autonomy):
    confirm_phrase: str = ""


class TrainReq(BaseModel):
    kind: Literal["lightgbm", "random_forest"] = "lightgbm"
    symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"], max_length=10)
    timeframe: Literal["15m", "30m", "1h", "4h"] = "1h"
    bars: int = Field(1000, ge=500, le=1000)
    horizon: int = Field(12, ge=1, le=96)


class PrefsReq(BaseModel):
    telegram_chat_id: str | None = Field(None, max_length=64, pattern=r"^-?[0-9]+$")
    email: str | None = Field(None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    alert_prefs: dict[str, list[Literal["telegram", "email"]]] = Field(default_factory=dict)


def create_app(state: App | None = None) -> FastAPI:
    st = state or App()
    api = FastAPI(title="Promovent", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    api.state.app = st

    def auth(min_role: str):
        def dep(request: Request, x_api_key: str | None = Header(None)):
            who = (x_api_key or "")[:8] + "|" + (request.client.host if request.client else "?")
            if not st.limiter.allow(who):
                raise HTTPException(429, "rate limit")
            if st.no_auth:
                request.state.key_hash, request.state.role = "dev", "admin"
                return "dev"
            role = None
            for k, r in st.keys.items():
                if x_api_key and hmac.compare_digest(k, x_api_key):
                    role = r
            if role is None:
                raise HTTPException(401, "missing or invalid X-API-Key")
            if ROLES[role] < ROLES[min_role]:
                raise HTTPException(403, f"requires {min_role}")
            request.state.key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
            request.state.role = role
            return role
        return dep

    @api.exception_handler(DataUnavailable)
    async def _du(_, e: DataUnavailable):
        return JSONResponse(status_code=503, content={"error": "market data unavailable", "detail": str(e)})

    @api.exception_handler(DatabaseUnavailable)
    async def _db(_, e: DatabaseUnavailable):
        return JSONResponse(status_code=503, content={"error": "database unavailable", "detail": str(e)})

    @api.exception_handler(DataValidationError)
    async def _dv(_, e: DataValidationError):
        return JSONResponse(status_code=422, content={"error": str(e)})

    @api.get("/", include_in_schema=False)
    def index():
        return {"service": "promovent-api", "version": __version__, "docs": "/api/docs",
                "frontend": "Next.js app (promovent/web), served separately"}

    @api.get("/api/health")
    def health():
        db, rd = st.store.health(), st.coord.health()
        return JSONResponse(status_code=200 if db["ok"] else 503, content={
            "ok": db["ok"], "version": __version__, "env": st.env, "database": db, "redis": rd,
            "workers": st.coord.heartbeats(), "notifications": st.notifier.status()})

    @api.get("/api/status")
    def status(_=Depends(auth("viewer"))):
        return {"mode": st.settings.mode.value, "source": st.source, "exchange": st.market.exchange,
                "live_trading": ("enabled: " + st.settings.mode.value) if st.settings.mode.is_live else "off (paper/observation mode)",
                "withdrawals": "never supported",
                "auth": "DISABLED (dev)" if st.no_auth else "api-key", "risk": st.settings.risk.model_dump(),
                "validated_strategies": sorted(st.agent.validated), "timeframes": TIMEFRAMES}

    @api.get("/api/exchanges/health")
    def ex_health(_=Depends(auth("viewer"))):
        return [get_adapter(n).health() for n in ADAPTERS]

    @api.get("/api/ohlcv")
    def ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = Query(500, ge=50, le=1000),
              _=Depends(auth("viewer"))):
        df, meta = st.market.ohlcv(symbol, timeframe, max(limit, 300))
        df = df.iloc[-limit:]
        s = analyze(df)
        return {"meta": meta.as_dict(), "gaps": df.attrs.get("gaps", 0),
                "candles": [{"time": int(t.value // 10**9), "open": r.open, "high": r.high, "low": r.low,
                             "close": r.close, "volume": r.volume} for t, r in df.iterrows()],
                "breaks": [{"time": int(t.value // 10**9), "kind": b} for t, b in s["break"].items() if b],
                "last_swing_high": _nan(s["last_sh"].iloc[-1]), "last_swing_low": _nan(s["last_sl"].iloc[-1])}

    @api.get("/api/analysis")
    def analysis(symbol: str = "BTC/USDT", timeframe: str = "1h", _=Depends(auth("viewer"))):
        return _clean(st.market.analysis(symbol, timeframe))

    @api.get("/api/regime")
    def regime(symbol: str = "BTC/USDT", timeframe: str = "1h", _=Depends(auth("viewer"))):
        df, meta = st.market.ohlcv(symbol, timeframe)
        r = classify(df).iloc[-1]
        return {"meta": meta.as_dict(), "regime": r["regime"], "tradeable": bool(r["tradeable"]),
                "adx": _nan(r["adx"]), "vol_percentile": _nan(r["vol_pct"])}

    @api.get("/api/scan")
    def scan(timeframe: str = "1h", _=Depends(auth("viewer"))):
        res = st.market.scan(tf=timeframe)
        for a in alerts_from_scan(res):
            st.store.add_alert_once(a["kind"], a["symbol"], a["message"])  # same event alerted once, not every refresh
        return _clean(res)

    @api.get("/api/alerts")
    def alerts(limit: int = Query(50, ge=1, le=500), _=Depends(auth("viewer"))):
        return st.store.alerts(limit)

    @api.get("/api/strategies")
    def strategies(_=Depends(auth("viewer"))):
        return [s.describe() | {"validated": s.name in st.agent.validated} for s in REGISTRY.values()]

    @api.post("/api/backtest")
    def backtest(req: BacktestReq, _=Depends(auth("viewer"))):
        strat = _strategy(req.strategy, req.params)
        df, meta = st.market.ohlcv(req.symbol, req.timeframe, req.bars)
        costs = Costs(req.fee_bps, req.spread_bps, req.slippage_bps, req.funding_rate_8h)
        res = run(df, strat, validate_symbol(req.symbol), req.initial, costs, st.settings.risk, req.timeframe)
        st.store.add(BacktestResult(strategy=strat.name, symbol=req.symbol, timeframe=req.timeframe, source=meta.source,
                                    params=strat.params, metrics=_clean(res.metrics)))
        eq = res.equity.iloc[:: max(1, len(res.equity) // 400)]
        return _clean({"meta": meta.as_dict(), "strategy": strat.describe(), "metrics": res.metrics,
                       "monte_carlo": monte_carlo(res.trades, req.initial, 500),
                       "equity": [{"time": int(t.value // 10**9), "value": float(v)} for t, v in eq.items()],
                       "trades": [t.as_dict() for t in res.trades[-200:]]})

    @api.post("/api/validate")
    def validate(req: BacktestReq, actor=Depends(auth("admin"))):
        strat = _strategy(req.strategy, req.params)
        df, meta = st.market.ohlcv(req.symbol, req.timeframe, req.bars)
        costs = Costs(req.fee_bps, req.spread_bps, req.slippage_bps, req.funding_rate_8h)
        res = run(df, strat, validate_symbol(req.symbol), req.initial, costs, st.settings.risk, req.timeframe)
        base = strat.params
        grid = [base] + [{**base, k: v * f} for k, v in base.items() for f in (0.8, 1.25)
                         if isinstance(v, (int, float)) and not isinstance(v, bool)][:8]
        grid = [{k: (int(round(v)) if isinstance(base[k], int) else v) for k, v in g.items()} for g in grid]
        wf = walk_forward(df, lambda p: get_strategy(req.strategy, p), grid, n_folds=3,
                          costs=costs, risk=st.settings.risk, tf=req.timeframe)
        mc = monte_carlo(res.trades, req.initial, 500)
        gate = ValidationGate().check(res.metrics, wf, mc)
        if gate["passed"]:
            st.agent.validated.add(req.strategy)
        with st.store.session() as s:
            row = s.query(StrategyRow).filter_by(name=req.strategy).one_or_none() or StrategyRow(name=req.strategy)
            row.params, row.validated, row.validation = strat.params, gate["passed"], _clean({"gate": gate, "source": meta.source})
            row.validated_at = datetime.now(timezone.utc)
            s.add(row)
        st.store.audit(str(actor), "validate_strategy", {"strategy": req.strategy, "source": meta.source, **gate})
        return _clean({"meta": meta.as_dict(), "metrics": res.metrics, "walk_forward": wf, "monte_carlo": mc, "gate": gate})

    @api.get("/api/portfolio")
    def portfolio(_=Depends(auth("viewer"))):
        snap = st.broker.snapshot()
        snap["trades"] = st.store.positions("paper", closed=True)
        snap["limits"] = {"daily_loss": st.risk.daily_loss(st.broker.state), "weekly_loss": st.risk.weekly_loss(st.broker.state),
                          "lockouts": st.risk.lockouts(st.broker.state)}
        return snap

    @api.post("/api/paper/order")
    def paper_order(req: OrderReq, actor=Depends(auth("trader"))):
        strat = _strategy(req.strategy, {})
        df, meta = st.market.ohlcv(req.symbol, req.timeframe)
        sg = strat.signals(df).iloc[-1]
        if not sg["side"]:
            return {"placed": False, "reason": f"{req.strategy} has no signal on the last closed {req.timeframe} bar"}
        price = float(df["close"].iloc[-1])
        sig = Signal(strat.name, validate_symbol(req.symbol), int(sg["side"]), price, float(sg["stop"]), float(sg["target"]),
                     df.index[-1], sg["reason"])
        try:
            return {"placed": True, **st.agent.execute(sig, price, actor=str(actor)), "meta": meta.as_dict()}
        except OrderRejected as e:
            raise HTTPException(409, str(e)) from e

    @api.post("/api/kill")
    def kill(req: KillReq, actor=Depends(auth("trader"))):
        st.agent.kill(str(actor), req.reason)
        return {"kill_switch": True, "reason": req.reason}

    @api.post("/api/kill/release")
    def release(actor=Depends(auth("admin"))):
        st.broker.state.kill_switch = False
        st.store.audit(str(actor), "kill_switch_released", {})
        return {"kill_switch": False}

    @api.get("/api/audit")
    def audit(limit: int = Query(100, ge=1, le=1000), _=Depends(auth("admin"))):
        return st.store.audit_log(limit)

    # ------------------------------------------------------------------ V2.5: live trading
    def _price(symbol: str) -> tuple[float, float, dict]:
        df, meta = st.market.ohlcv(symbol, "1m", 60)
        return float(df["close"].iloc[-1]), meta.timestamp_ms / 1000, meta.as_dict()

    def _sig(req: OrderReq) -> Signal | None:
        strat = _strategy(req.strategy, {})
        df, _ = st.market.ohlcv(req.symbol, req.timeframe)
        sg = strat.signals(df).iloc[-1]
        if not sg["side"]:
            return None
        return Signal(strat.name, validate_symbol(req.symbol), int(sg["side"]), float(df["close"].iloc[-1]),
                      float(sg["stop"]), float(sg["target"]), df.index[-1], sg["reason"])

    @api.get("/api/live/status")
    def live_status(_=Depends(auth("viewer"))):
        out = {"mode": st.settings.mode.value, "live_enabled": st.settings.live_trading_enabled,
               "exchange": os.getenv("PROMOVENT_LIVE_EXCHANGE", "binance"), "autonomy": st.autonomy.model_dump(),
               "withdrawals": "never supported"}
        try:
            eng = st.live()
        except ExecError as e:
            return out | {"ready": False, "problem": str(e)}
        out |= {"testnet": eng.client.testnet}
        try:
            p = eng.permissions(max_age=0)
            out |= {"ready": p.can_trade and p.withdrawals_enabled is not True, "can_trade": p.can_trade,
                    "withdrawals_enabled": p.withdrawals_enabled, "permission_detail": p.detail}
        except ExecError as e:
            out |= {"ready": False, "problem": str(e)}
        return out

    @api.post("/api/live/preflight")
    def live_preflight(req: OrderReq, _=Depends(auth("trader"))):
        sig = _sig(req)
        if sig is None:
            return {"ok": False, "failed": [f"{req.strategy} has no signal on the last closed {req.timeframe} bar"]}
        try:
            eng = st.live()
        except ExecError as e:
            return {"ok": False, "failed": [f"credentials: {e}"]}
        price, ts, meta = _price(req.symbol)
        return eng.preflight(sig, price, ts).as_dict() | {"meta": meta}

    @api.post("/api/live/propose")
    def live_propose(req: OrderReq, actor=Depends(auth("trader"))):
        sig = _sig(req)
        if sig is None:
            raise HTTPException(409, f"{req.strategy} has no signal on the last closed {req.timeframe} bar")
        try:
            price, ts, meta = _price(req.symbol)
            return st.live().propose(sig, price, ts, str(actor)) | {"meta": meta}
        except ExecError as e:
            raise HTTPException(409, str(e)) from e
        except LiveOrderRejected as e:
            raise HTTPException(409, {"rejected": str(e), "preflight": e.preflight.as_dict() if e.preflight else None}) from e


    @api.post("/api/live/confirm")
    def live_confirm(req: ConfirmReq, actor=Depends(auth("trader"))):
        try:
            price, ts, _ = _price(req.symbol)
            res = st.live().confirm(req.token, price, ts, str(actor))
        except ExecError as e:
            raise HTTPException(409, str(e)) from e
        except LiveOrderRejected as e:
            raise HTTPException(409, {"rejected": str(e), "preflight": e.preflight.as_dict() if e.preflight else None}) from e
        st.notifier.notify("execution", {**res, "symbol": req.symbol, "qty": res["filled_qty"],
                                         "testnet": " (testnet)" if res["testnet"] else ""}, _users())
        return res


    @api.post("/api/live/autonomy")
    def live_autonomy(req: AutonomyReq, actor=Depends(auth("admin"))):
        if req.active and req.confirm_phrase != "I ACCEPT AUTONOMOUS LIVE TRADING":
            raise HTTPException(400, "set confirm_phrase to 'I ACCEPT AUTONOMOUS LIVE TRADING' to activate")
        st.autonomy = Autonomy(**req.model_dump(exclude={"confirm_phrase"}))
        if st._live:
            st._live.autonomy = st.autonomy
        st.store.audit(str(actor), "autonomy_changed", st.autonomy.model_dump())
        return st.autonomy.model_dump()

    @api.post("/api/live/reconcile")
    def live_reconcile(_=Depends(auth("admin"))):
        try:
            return st.live().reconcile()
        except ExecError as e:
            raise HTTPException(409, str(e)) from e

    @api.get("/api/live/orders")
    def live_orders(_=Depends(auth("viewer"))):
        return [o for o in st.store.orders(limit=200) if o["venue"] != "paper"]

    # ------------------------------------------------------------------ V2.5: streaming, intel, ML, settings
    @api.get("/api/stream")
    def stream(_=Depends(auth("viewer"))):
        snap = st.coord.get("stream_snapshot")
        if not snap:
            return {"available": False, "reason": "no stream snapshot in Redis: worker not running, Redis down, or exchange unreachable"}
        return {"available": True, **snap}

    @api.get("/api/whales")
    def whales(min_usd: int = Query(1_000_000, ge=100_000), _=Depends(auth("viewer"))):
        cached = st.coord.get(f"whales:{min_usd}")
        if cached:
            return cached
        from .intel import ProviderUnavailable
        from .intel.whale import Blockchair, Etherscan, WhaleAlert, WhaleSummary
        txs, errors = [], {}
        bc = Blockchair()
        for name, f in (("whale-alert", lambda: WhaleAlert().recent(min_usd)), ("etherscan", lambda: Etherscan().recent()),
                        ("blockchair-btc", lambda: bc.recent("bitcoin", min_usd)), ("blockchair-eth", lambda: bc.recent("ethereum", min_usd))):
            try:
                txs += f()
            except ProviderUnavailable as e:
                errors[name] = str(e)
        s = WhaleSummary(txs)
        out = {"transactions": [t.as_dict() for t in sorted(txs, key=lambda t: -t.ts)], "flows": s.flows(),
               "clusters": s.clusters(), "errors": errors, "fetched_at": datetime.now(timezone.utc).isoformat()}
        if txs:
            st.coord.set(f"whales:{min_usd}", out, 60)
        return out

    @api.get("/api/news")
    def news(_=Depends(auth("viewer"))):
        cached = st.coord.get("news")
        if cached:
            return cached
        from .intel.news import collect
        out = collect() | {"fetched_at": datetime.now(timezone.utc).isoformat()}
        if out["items"]:
            st.coord.set("news", out, 120)
        return out

    @api.get("/api/ml/models")
    def ml_models(_=Depends(auth("viewer"))):
        from .ml.train import list_models
        return list_models()


    @api.post("/api/ml/train")
    def ml_train(req: TrainReq, actor=Depends(auth("admin"))):
        from .ml.dataset import prepare
        from .ml.train import train
        frames = {s: st.market.ohlcv(s, req.timeframe, req.bars)[0] for s in req.symbols}
        meta = train(prepare(frames, req.timeframe, req.horizon, source=st.source), req.kind)
        st.store.audit(str(actor), "ml_train", {"version": meta["version"], "source": st.source})
        return _clean({k: meta[k] for k in ("version", "kind", "trained_at", "dataset", "validation", "feature_importance", "usage")})

    @api.get("/api/ml/predict")
    def ml_predict(version: str, symbol: str = "BTC/USDT", timeframe: str = "1h", _=Depends(auth("viewer"))):
        from .ml.train import predict
        df, meta = st.market.ohlcv(symbol, timeframe, 600)
        try:
            return _clean(predict(version, df, meta.source) | {"meta": meta.as_dict()})
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @api.get("/api/risk/events")
    def risk_events(_=Depends(auth("viewer"))):
        return st.store.risk_events()

    def _me(request: Request) -> User:
        kh = getattr(request.state, "key_hash", "dev")
        with st.store.session() as s:
            u = s.query(User).filter_by(api_key_hash=kh).one_or_none()
            if u is None:
                u = User(username=f"user-{kh[:8]}", role=getattr(request.state, "role", "viewer"), api_key_hash=kh, alert_prefs={})
                s.add(u)
                s.flush()
            s.expunge(u)
            return u

    def _users() -> list[dict]:
        return [r for r in st.store.list(User, 100)]


    @api.get("/api/settings/alerts")
    def get_prefs(request: Request, _=Depends(auth("viewer"))):
        u = _me(request)
        from .notify import DEFAULT_PREFS
        return {"telegram_chat_id": u.telegram_chat_id, "email": u.email, "alert_prefs": u.alert_prefs or DEFAULT_PREFS,
                "events": list(EVENTS), "channels": st.notifier.status()}

    @api.put("/api/settings/alerts")
    def put_prefs(req: PrefsReq, request: Request, _=Depends(auth("viewer"))):
        bad = [e for e in req.alert_prefs if e not in EVENTS]
        if bad:
            raise HTTPException(422, f"unknown events {bad}")
        u = _me(request)
        with st.store.session() as s:
            row = s.get(User, u.id)
            row.telegram_chat_id, row.email, row.alert_prefs = req.telegram_chat_id, req.email, req.alert_prefs
        return get_prefs(request)

    @api.post("/api/settings/alerts/test")
    def test_alert(request: Request, _=Depends(auth("viewer"))):
        u = _me(request)
        return st.notifier.notify("system_health", {"component": "notifications", "state": "test",
                                                    "detail": "Test message from Promovent settings."},
                                  [{"id": u.id, "username": u.username, "telegram_chat_id": u.telegram_chat_id, "email": u.email,
                                    "alert_prefs": {"system_health": ["telegram", "email"]}}])

    @api.get("/api/notifications")
    def notifications(_=Depends(auth("viewer"))):
        return st.store.notifications()

    return api


def _strategy(name: str, params: dict):
    try:
        return get_strategy(name, params)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


def _nan(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


app = create_app() if os.getenv("PROMOVENT_NO_AUTOAPP") != "1" else None
