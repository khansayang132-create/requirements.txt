"""Redis: shared rate limiting, cache, worker locks and heartbeats.

If Redis is unreachable the process keeps working in a DEGRADED mode:
rate limiting and cache fall back to in-process memory (per instance, not
shared), and `health()` reports it. Locks fail CLOSED: without Redis a worker
cannot prove it is the only one, so `acquire_lock` returns False and the job
does not run.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

import redis


class Coord:
    def __init__(self, url: str | None = None):
        self.url = url or os.getenv("PROMOVENT_REDIS_URL", "")
        self.r = redis.Redis.from_url(self.url, socket_timeout=1.0, socket_connect_timeout=1.0) if self.url else None
        self._mem: dict[str, tuple[float, float]] = {}
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self.last_error: str | None = None

    # --- health ---------------------------------------------------------------
    def available(self) -> bool:
        if not self.r:
            return False
        try:
            return bool(self.r.ping())
        except redis.RedisError as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return False

    def health(self) -> dict:
        if not self.r:
            return {"ok": False, "mode": "memory", "error": "PROMOVENT_REDIS_URL not set"}
        ok = self.available()
        return {"ok": ok, "mode": "redis" if ok else "degraded-memory", "error": None if ok else self.last_error}

    # --- rate limiting (token bucket, atomic in Lua) -----------------------------
    _LUA = """
    local k = KEYS[1]
    local rate, burst, now = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
    local v = redis.call('HMGET', k, 't', 'ts')
    local tokens = tonumber(v[1]) or burst
    local ts = tonumber(v[2]) or now
    tokens = math.min(burst, tokens + (now - ts) * rate)
    local ok = 0
    if tokens >= 1 then tokens = tokens - 1; ok = 1 end
    redis.call('HSET', k, 't', tokens, 'ts', now)
    redis.call('EXPIRE', k, math.ceil(burst / rate) + 1)
    return ok
    """

    def allow(self, who: str, rate: float = 5.0, burst: int = 30) -> bool:
        now = time.time()
        if self.r:
            try:
                return bool(self.r.eval(self._LUA, 1, f"pv:rl:{who}", rate, burst, now))
            except redis.RedisError as e:
                self.last_error = f"{type(e).__name__}: {e}"
        with self._lock:
            tokens, last = self._mem.get(who, (burst, now))
            tokens = min(burst, tokens + (now - last) * rate)
            if tokens < 1:
                self._mem[who] = (tokens, now)
                return False
            self._mem[who] = (tokens - 1, now)
            return True

    # --- cache ------------------------------------------------------------------
    def get(self, key: str):
        if self.r:
            try:
                v = self.r.get(f"pv:c:{key}")
                return json.loads(v) if v else None
            except redis.RedisError as e:
                self.last_error = str(e)
        hit = self._cache.get(key)
        return json.loads(hit[1]) if hit and hit[0] > time.time() else None

    def set(self, key: str, value, ttl: float) -> None:
        data = json.dumps(value, default=str)
        if self.r:
            try:
                self.r.set(f"pv:c:{key}", data, px=int(ttl * 1000))
                return
            except redis.RedisError as e:
                self.last_error = str(e)
        self._cache[key] = (time.time() + ttl, data)

    # --- coordination -------------------------------------------------------------
    def acquire_lock(self, name: str, ttl: float = 60) -> str | None:
        """Returns a token if this process holds the lock. Fails closed without Redis."""
        if not self.r:
            return None
        token = uuid.uuid4().hex
        try:
            return token if self.r.set(f"pv:lock:{name}", token, nx=True, px=int(ttl * 1000)) else None
        except redis.RedisError as e:
            self.last_error = str(e)
            return None

    def release_lock(self, name: str, token: str) -> None:
        if not self.r:
            return
        lua = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"
        try:
            self.r.eval(lua, 1, f"pv:lock:{name}", token)
        except redis.RedisError:
            pass

    def heartbeat(self, who: str, info: dict, ttl: float = 90) -> bool:
        payload = {"ts": time.time(), **info}
        if self.r:
            try:
                self.r.set(f"pv:hb:{who}", json.dumps(payload, default=str), px=int(ttl * 1000))
                return True
            except redis.RedisError as e:
                self.last_error = str(e)
        return False

    def heartbeats(self) -> dict:
        if not self.r:
            return {}
        try:
            out = {}
            for k in self.r.scan_iter("pv:hb:*"):
                v = self.r.get(k)
                if v:
                    out[k.decode().split(":", 2)[2]] = json.loads(v)
            return out
        except redis.RedisError:
            return {}
