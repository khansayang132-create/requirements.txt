"""FastAPI service. Run: uvicorn promovent.api:app --host 127.0.0.1 --port 8000

Auth: header `X-API-Key`. Keys and roles come from PROMOVENT_API_KEYS
("key1:admin,key2:trader,key3:viewer"); keys are compared in constant time and
never logged. Roles: viewer (read) < trader (paper orders, engage kill switch)
< admin (validate strategies, audit log). PROMOVENT_DEV_NO_AUTH=yes disables
auth for local development only; /api/status reports it.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .backtest import Costs, ValidationGate, monte_carlo, run, walk_forward
from .config import Mode, Settings
from .data.exchanges import ADAPTERS, get_adapter
from .models import DataValidationError, Signal, TIMEFRAMES, validate_symbol
from .paper import ExecutionAgent, OrderRejected, PaperBroker
from .risk import RiskEngine
from .service import DataUnavailable, MarketService, alerts_from_scan
from .storage import Store
from .strategies import REGISTRY, get_strategy
from .ta.regime import classify
from .ta.structure import analyze

ROLES = {"viewer": 0, "trader": 1, "admin": 2}
STATIC = Path(__file__).resolve().parent / "static"


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


class App:
    def __init__(self, settings: Settings | None = None, source: str | None = None, db: str | None = None,
                 keys: dict[str, str] | None = None, no_auth: bool | None = None):
        self.settings = settings or Settings(mode=Mode(os.getenv("PROMOVENT_MODE", "paper")))
        self.source = source or os.getenv("PROMOVENT_SOURCE", "live")
        self.market = MarketService(source=self.source, exchange=os.getenv("PROMOVENT_EXCHANGE", "binance"))
        self.store = Store(db or os.getenv("PROMOVENT_DB", ":memory:"))
        self.risk = RiskEngine(self.settings.risk)
        self.broker = PaperBroker(self.store)
        self.agent = ExecutionAgent(self.settings, self.risk, self.broker, self.store)
        self.keys = keys if keys is not None else _parse_keys(os.getenv("PROMOVENT_API_KEYS", ""))
        self.no_auth = no_auth if no_auth is not None else os.getenv("PROMOVENT_DEV_NO_AUTH", "") == "yes"
        self.limiter = RateLimiter()


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


def create_app(state: App | None = None) -> FastAPI:
    st = state or App()
    api = FastAPI(title="Promovent", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    api.state.app = st
    api.mount("/static", StaticFiles(directory=STATIC), name="static")

    def auth(min_role: str):
        def dep(request: Request, x_api_key: str | None = Header(None)):
            who = (x_api_key or "")[:8] + "|" + (request.client.host if request.client else "?")
            if not st.limiter.allow(who):
                raise HTTPException(429, "rate limit")
            if st.no_auth:
                return "dev"
            role = None
            for k, r in st.keys.items():
                if x_api_key and hmac.compare_digest(k, x_api_key):
                    role = r
            if role is None:
                raise HTTPException(401, "missing or invalid X-API-Key")
            if ROLES[role] < ROLES[min_role]:
                raise HTTPException(403, f"requires {min_role}")
            return role
        return dep

    @api.exception_handler(DataUnavailable)
    async def _du(_, e: DataUnavailable):
        return JSONResponse(status_code=503, content={"error": "market data unavailable", "detail": str(e)})

    @api.exception_handler(DataValidationError)
    async def _dv(_, e: DataValidationError):
        return JSONResponse(status_code=422, content={"error": str(e)})

    @api.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @api.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @api.get("/api/status")
    def status(_=Depends(auth("viewer"))):
        return {"mode": st.settings.mode.value, "source": st.source, "exchange": st.market.exchange,
                "live_trading": "not implemented in this build", "withdrawals": "never supported",
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
            seen = st.store.query("SELECT 1 FROM alerts WHERE kind=? AND symbol=? AND message=? AND ts > datetime('now', '-6 hours')",
                                  (a["kind"], a["symbol"], a["message"]))
            if not seen:  # same event is alerted once, not on every refresh
                st.store.execute("INSERT INTO alerts (ts, kind, symbol, message) VALUES (datetime('now'),?,?,?)",
                                 (a["kind"], a["symbol"], a["message"]))
        return _clean(res)

    @api.get("/api/alerts")
    def alerts(limit: int = Query(50, ge=1, le=500), _=Depends(auth("viewer"))):
        return st.store.query("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))

    @api.get("/api/strategies")
    def strategies(_=Depends(auth("viewer"))):
        return [s.describe() | {"validated": s.name in st.agent.validated} for s in REGISTRY.values()]

    @api.post("/api/backtest")
    def backtest(req: BacktestReq, _=Depends(auth("viewer"))):
        strat = _strategy(req.strategy, req.params)
        df, meta = st.market.ohlcv(req.symbol, req.timeframe, req.bars)
        costs = Costs(req.fee_bps, req.spread_bps, req.slippage_bps, req.funding_rate_8h)
        res = run(df, strat, validate_symbol(req.symbol), req.initial, costs, st.settings.risk, req.timeframe)
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
        st.store.audit(str(actor), "validate_strategy", {"strategy": req.strategy, "source": meta.source, **gate})
        return _clean({"meta": meta.as_dict(), "metrics": res.metrics, "walk_forward": wf, "monte_carlo": mc, "gate": gate})

    @api.get("/api/portfolio")
    def portfolio(_=Depends(auth("viewer"))):
        snap = st.broker.snapshot()
        snap["trades"] = st.store.query("SELECT * FROM paper_trades ORDER BY id DESC LIMIT 100")
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
        return st.store.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

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
