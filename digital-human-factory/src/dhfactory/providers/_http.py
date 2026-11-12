"""Small shared HTTP helper: timeouts, status mapping, and no secrets in error text."""

from __future__ import annotations

import time

import httpx

from ..errors import ProviderError, ProviderNotConfigured, ProviderUnreachable
from ..utils.redaction import redact


def request(provider: str, method: str, url: str, *, headers: dict, timeout: float, client: httpx.Client | None = None, **kw) -> dict:
    c = client or httpx.Client(timeout=timeout)
    try:
        r = c.request(method, url, headers=headers, **kw)
    except httpx.ProxyError as e:
        raise ProviderUnreachable(f"{provider}: network/proxy refused the connection ({type(e).__name__})") from e
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        raise ProviderError(provider, f"connection problem: {type(e).__name__}", transient=True) from e
    finally:
        if client is None:
            c.close()
    if r.status_code in (401, 403):
        raise ProviderNotConfigured(provider, f"credentials rejected (HTTP {r.status_code})")
    if r.status_code == 429 or r.status_code >= 500:
        raise ProviderError(provider, f"HTTP {r.status_code}", transient=True)
    if r.status_code >= 400:
        raise ProviderError(provider, f"HTTP {r.status_code}: {redact(r.text[:300])}")
    return r.json() if r.content else {}


def poll(fn, *, done, failed, interval: float = 5.0, timeout: float = 900.0, sleep=time.sleep) -> dict:
    t0 = time.monotonic()
    while True:
        data = fn()
        if done(data):
            return data
        if failed(data):
            raise ProviderError("poll", f"job failed: {redact(str(data)[:300])}")
        if time.monotonic() - t0 > timeout:
            raise ProviderError("poll", "timed out waiting for the job", transient=True)
        sleep(interval)


def download(url: str, out, timeout: float = 300.0, client: httpx.Client | None = None):
    c = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        with c.stream("GET", url) as r:
            r.raise_for_status()
            with open(out, "wb") as fh:
                fh.writelines(r.iter_bytes())
    finally:
        if client is None:
            c.close()
    return out
