"""Background worker: `python -m promovent.worker`

Jobs (each guarded by a Redis lock so several worker replicas never double-run them):
  stream      WebSocket market stream for PROMOVENT_STREAM_SYMBOLS; snapshot published to Redis every 2 s
  scan        market scan every PROMOVENT_SCAN_MINUTES; new alerts stored and sent per user preferences
  reconcile   live orders vs exchange every 60 s (live modes only)
  snapshot    paper portfolio snapshot every 5 min
  heartbeat   worker status to Redis every 15 s (read by /api/health)
SIGTERM/SIGINT stop new work, close sockets and exit within ~5 s (Docker's default grace is 10 s).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import time

from .api import App
from .db.models import PortfolioSnapshot, User
from .execution.clients import ExecError
from .market_data.market_stream import MarketStream
from .service import DataUnavailable, alerts_from_scan

log = logging.getLogger("promovent.worker")


class Worker:
    def __init__(self, app: App | None = None):
        self.app = app or App()
        self.name = f"worker-{socket.gethostname()}-{os.getpid()}"
        self.stop = asyncio.Event()
        self.stream: MarketStream | None = None
        self.jobs: dict[str, dict] = {}
        self.started = time.time()

    def _mark(self, job: str, ok: bool, detail: str = ""):
        self.jobs[job] = {"ok": ok, "at": time.time(), "detail": detail[:300]}

    async def _every(self, seconds: float, job: str, fn, lock: bool = True):
        while not self.stop.is_set():
            token = self.app.coord.acquire_lock(job, ttl=max(seconds, 30)) if lock else "nolock"
            if token or not self.app.coord.r:  # no Redis configured at all: single-instance mode
                try:
                    detail = await asyncio.to_thread(fn)
                    self._mark(job, True, str(detail or ""))
                except Exception as e:  # a job failure must not kill the worker
                    log.exception("job %s failed", job)
                    self._mark(job, False, f"{type(e).__name__}: {e}")
                finally:
                    if token and token != "nolock":
                        self.app.coord.release_lock(job, token)
            else:
                self._mark(job, True, "skipped: another worker holds the lock or Redis is down")
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass

    # ---- jobs ---------------------------------------------------------------
    def scan(self):
        try:
            res = self.app.market.scan(tf=os.getenv("PROMOVENT_SCAN_TF", "1h"))
        except DataUnavailable as e:
            return f"data unavailable: {e}"
        new = [a for a in alerts_from_scan(res) if self.app.store.add_alert_once(a["kind"], a["symbol"], a["message"])]
        users = self.app.store.list(User, 100)
        for a in new:
            if a["kind"] == "a_plus_setup":
                self.app.notifier.notify("signal", {"symbol": a["symbol"], "side": "", "strategy": "scanner", "score": a["message"]}, users)
            if a["kind"] == "data_outage":
                self.app.notifier.notify("system_health", {"component": a["symbol"], "state": "data outage", "detail": a["message"]}, users)
        return f"{len(res['results'])} symbols, {len(res['errors'])} errors, {len(new)} new alerts"

    def reconcile(self):
        if not self.app.settings.mode.is_live:
            return "not in a live mode"
        try:
            return self.app.live().reconcile()
        except ExecError as e:
            return f"live engine unavailable: {e}"

    def snapshot(self):
        snap = self.app.broker.snapshot()
        self.app.store.add(PortfolioSnapshot(venue="paper", equity=snap["equity"], cash=snap["cash"], heat=snap["heat"],
                                             drawdown=snap["drawdown"], positions=snap["positions"]))
        return f"equity {snap['equity']:.2f}"

    def heartbeat(self):
        info = {"name": self.name, "uptime_s": round(time.time() - self.started), "jobs": self.jobs,
                "stream": self.stream.conn_state() if self.stream else "disabled"}
        ok = self.app.coord.heartbeat(self.name, info)
        return "ok" if ok else "redis unavailable"

    def publish_stream(self):
        if self.stream:
            self.app.coord.set("stream_snapshot", self.stream.snapshot() | {"published_at": time.time()}, 10)

    # ---- lifecycle ------------------------------------------------------------
    async def run(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        tasks = [asyncio.create_task(self._every(15, "heartbeat", self.heartbeat, lock=False)),
                 asyncio.create_task(self._every(float(os.getenv("PROMOVENT_SCAN_MINUTES", "5")) * 60, "scan", self.scan)),
                 asyncio.create_task(self._every(60, "reconcile", self.reconcile)),
                 asyncio.create_task(self._every(300, "snapshot", self.snapshot))]
        if self.app.source == "live" and os.getenv("PROMOVENT_STREAM", "yes") == "yes":
            syms = os.getenv("PROMOVENT_STREAM_SYMBOLS", "BTC/USDT,ETH/USDT").split(",")
            self.stream = MarketStream(os.getenv("PROMOVENT_EXCHANGE", "binance"), syms)
            tasks.append(asyncio.create_task(self.stream.run()))
            tasks.append(asyncio.create_task(self._every(2, "stream_publish", self.publish_stream, lock=False)))
        log.info("worker %s started (%d jobs)", self.name, len(tasks))
        await self.stop.wait()
        log.info("worker %s stopping", self.name)
        if self.stream:
            self.stream.stop()
        await asyncio.wait(tasks, timeout=5)
        for t in tasks:
            t.cancel()
        log.info("worker %s stopped", self.name)


def main():
    logging.basicConfig(level=os.getenv("PROMOVENT_LOG_LEVEL", "INFO"),
                        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
    asyncio.run(Worker().run())


if __name__ == "__main__":
    main()
