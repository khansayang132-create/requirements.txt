"""One managed WebSocket connection.

- Reconnects forever with exponential backoff (1 s doubling to 60 s, +-20 % jitter);
  HTTP 429/418 on the handshake waits at least 60 s.
- Heartbeat: protocol pings (ping_interval) plus the venue's app-level ping if it has one.
- Stale detection: no message for `stale_after` seconds => status STALE, socket closed, reconnect.
- Outgoing messages (subscriptions) are rate limited to the venue's documented limit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import websockets

log = logging.getLogger("promovent.ws")


@dataclass
class ConnStatus:
    url: str
    state: str = "INIT"           # INIT | CONNECTING | CONNECTED | STALE | BACKOFF | STOPPED
    connected_since: float | None = None
    last_message: float | None = None
    reconnects: int = 0
    messages: int = 0
    last_error: str | None = None
    stale_events: int = 0

    def as_dict(self) -> dict:
        now = time.time()
        return {"url": self.url.split("?")[0], "state": self.state, "reconnects": self.reconnects, "messages": self.messages,
                "seconds_since_message": round(now - self.last_message, 1) if self.last_message else None,
                "last_error": self.last_error, "stale_events": self.stale_events}


@dataclass
class WSConnection:
    url: str
    subscriptions: list
    on_message: Callable[[str | bytes], Awaitable[None] | None]
    app_ping: Callable[[], str | None] = lambda: None
    app_ping_interval: float | None = None
    stale_after: float = 30.0
    max_msgs_per_sec: float = 5.0
    backoff_max: float = 60.0
    status: ConnStatus = field(init=False)
    _stop: asyncio.Event = field(init=False)

    def __post_init__(self):
        self.status = ConnStatus(self.url)
        self._stop = asyncio.Event()

    async def _send_limited(self, ws, msgs):
        gap = 1.0 / self.max_msgs_per_sec
        for m in msgs:
            await ws.send(m if isinstance(m, str) else json.dumps(m))
            await asyncio.sleep(gap)

    async def _pinger(self, ws):
        while True:
            await asyncio.sleep(self.app_ping_interval)
            msg = self.app_ping()
            if msg:
                await ws.send(msg)

    async def run(self):
        delay = 1.0
        while not self._stop.is_set():
            self.status.state = "CONNECTING"
            pinger = None
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20, open_timeout=10,
                                              close_timeout=1, max_size=2**23) as ws:
                    self.status.state, self.status.connected_since = "CONNECTED", time.time()
                    self.status.last_error = None
                    delay = 1.0
                    await self._send_limited(ws, self.subscriptions)
                    if self.app_ping_interval:
                        pinger = asyncio.create_task(self._pinger(ws))
                    stop_wait = asyncio.create_task(self._stop.wait())
                    try:
                        while not self._stop.is_set():
                            recv = asyncio.create_task(ws.recv())
                            done, _ = await asyncio.wait({recv, stop_wait}, timeout=self.stale_after,
                                                         return_when=asyncio.FIRST_COMPLETED)
                            if recv not in done:
                                recv.cancel()
                                if self._stop.is_set():
                                    break
                                self.status.state = "STALE"
                                self.status.stale_events += 1
                                self.status.last_error = f"no data for {self.stale_after:g}s"
                                break
                            raw = recv.result()
                            self.status.last_message = time.time()
                            self.status.messages += 1
                            r = self.on_message(raw)
                            if asyncio.iscoroutine(r):
                                await r
                    finally:
                        stop_wait.cancel()
            except websockets.InvalidStatus as e:
                code = e.response.status_code
                self.status.last_error = f"handshake HTTP {code}"
                if code in (418, 429):
                    delay = max(delay, 60.0)
            except (OSError, websockets.WebSocketException, ValueError) as e:
                self.status.last_error = f"{type(e).__name__}: {e}"[:300]
            finally:
                if pinger:
                    pinger.cancel()
            if self._stop.is_set():
                break
            self.status.reconnects += 1
            self.status.state = "BACKOFF"
            wait = min(delay, self.backoff_max) * random.uniform(0.8, 1.2)
            log.warning("ws %s reconnecting in %.1fs: %s", self.url.split("?")[0], wait, self.status.last_error)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, self.backoff_max)
        self.status.state = "STOPPED"

    def stop(self):
        self._stop.set()
