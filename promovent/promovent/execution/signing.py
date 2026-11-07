"""Request signing, exactly as each exchange documents it."""
from __future__ import annotations

import base64
import hashlib
import hmac


def binance(secret: str, query: str) -> str:
    """HMAC-SHA256 of the full query string, hex."""
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def bybit(secret: str, timestamp_ms: str, api_key: str, recv_window: str, payload: str) -> str:
    """v5: HMAC-SHA256 of timestamp + api_key + recv_window + (query string | JSON body), hex."""
    return hmac.new(secret.encode(), f"{timestamp_ms}{api_key}{recv_window}{payload}".encode(), hashlib.sha256).hexdigest()


def okx(secret: str, timestamp_iso: str, method: str, request_path: str, body: str = "") -> str:
    """v5: base64(HMAC-SHA256 of timestamp + METHOD + requestPath(with query) + body)."""
    msg = f"{timestamp_iso}{method.upper()}{request_path}{body}".encode()
    return base64.b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode()
