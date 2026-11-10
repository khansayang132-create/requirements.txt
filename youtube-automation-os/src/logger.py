"""Structured JSON-lines logging with request IDs and secret redaction.

Every record has: timestamp, request_id, operation, and whichever of endpoint,
http_status, error_class, retry_count, result the caller supplies. Records go to
``logs/ytaos.jsonl`` (one JSON object per line) and a short human line goes to stderr.

Redaction is applied to every record before it is written, so a caller that
accidentally passes a credentials dict still cannot leak a token into the log.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

SENSITIVE_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "openai_api_key",
    "code",
}

# Shapes of Google credentials: access tokens (ya29.), refresh tokens (1//),
# client secrets (GOCSPX-), API keys (AIza), plus bearer headers.
_SECRET_PATTERNS = [
    re.compile(r"ya29\.[0-9A-Za-z_\-\.]+"),
    re.compile(r"1//[0-9A-Za-z_\-]{10,}"),
    re.compile(r"GOCSPX-[0-9A-Za-z_\-]+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)bearer\s+[0-9A-Za-z_\-\.]+"),
    re.compile(r"sk-[0-9A-Za-z_\-]{16,}"),
]

REDACTED = "***REDACTED***"


def redact(value: Any) -> Any:
    """Return a copy of ``value`` with secret-looking keys and strings masked."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_KEYS and v not in (None, ""):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value
    return value


def new_request_id() -> str:
    """Create a request ID and make it current for this context."""
    rid = uuid.uuid4().hex[:12]
    _request_id.set(rid)
    return rid


def current_request_id() -> str:
    rid = _request_id.get()
    return rid if rid else new_request_id()


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


class StructuredLogger:
    def __init__(self, path: Path | None = None, level: str | None = None, echo: bool = True):
        self.path = Path(path) if path else None
        self.level = _LEVELS.get((level or os.getenv("LOG_LEVEL") or "INFO").upper(), 20)
        self.echo = echo

    def log(self, level: str, operation: str, message: str = "", **fields: Any) -> dict:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": level,
            "request_id": fields.pop("request_id", None) or current_request_id(),
            "operation": operation,
        }
        if message:
            record["message"] = message
        record.update({k: v for k, v in fields.items() if v is not None})
        record = redact(record)
        if _LEVELS.get(level, 20) < self.level:
            return record
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        if self.echo and (_LEVELS.get(level, 20) >= 30 or self.level <= 10):
            extras = " ".join(
                f"{k}={record[k]}"
                for k in ("endpoint", "http_status", "error_class", "retry_count", "result")
                if k in record
            )
            print(
                f"[{record['level']}] {record['request_id']} {operation}: {record.get('message', '')} {extras}".rstrip(),
                file=sys.stderr,
            )
        return record

    def debug(self, operation: str, message: str = "", **f: Any) -> dict:
        return self.log("DEBUG", operation, message, **f)

    def info(self, operation: str, message: str = "", **f: Any) -> dict:
        return self.log("INFO", operation, message, **f)

    def warning(self, operation: str, message: str = "", **f: Any) -> dict:
        return self.log("WARNING", operation, message, **f)

    def error(self, operation: str, message: str = "", **f: Any) -> dict:
        return self.log("ERROR", operation, message, **f)


_default: StructuredLogger | None = None


def get_logger() -> StructuredLogger:
    """Process-wide logger writing to ``<root>/logs/ytaos.jsonl`` (override with YTAOS_LOG_PATH)."""
    global _default
    if _default is None:
        from .config import project_root

        path = os.getenv("YTAOS_LOG_PATH") or str(project_root() / "logs" / "ytaos.jsonl")
        _default = StructuredLogger(Path(path))
    return _default


def set_logger(logger: StructuredLogger | None) -> None:
    global _default
    _default = logger
