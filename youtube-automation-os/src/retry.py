"""Error classification and bounded retries with exponential backoff and full jitter.

Policy (see README "Reliability"):

| HTTP / condition                         | Class            | Action                              |
|------------------------------------------|------------------|-------------------------------------|
| 401                                      | auth             | refresh token once, then fail       |
| 403 quotaExceeded / dailyLimitExceeded    | quota            | stop, mark bucket exhausted, no retry |
| 403 uploadLimitExceeded                  | quota            | stop (channel upload limit)         |
| 403 rateLimitExceeded / userRateLimit…   | rate_limit       | backoff + retry                     |
| 403 insufficientPermissions / forbidden  | permission       | fail with scope/ownership hint      |
| 404                                      | not_found        | fail                                |
| 429                                      | rate_limit       | backoff (honours Retry-After)       |
| 500 502 503 504                          | server           | backoff + retry                     |
| connection error / timeout               | network          | backoff + retry (idempotent ops only) |
| other 4xx                                | client           | fail                                |

Non-idempotent operations (``videos.insert`` initiation) are never blindly retried on a
network error: the caller must check remote state first. ``RetryPolicy.run`` takes an
``idempotent`` flag for that reason.
"""

from __future__ import annotations

import json
import random
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .exceptions import APIError, QuotaExceededError
from .logger import get_logger


class ErrorClass(str, Enum):
    AUTH = "auth"
    QUOTA = "quota"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    NETWORK = "network"
    CLIENT = "client"
    UNKNOWN = "unknown"


QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded", "dailyLimitExceededUnreg"}
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "rateLimitExceededUnreg"}
PERMISSION_REASONS = {"insufficientPermissions", "forbidden", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", "youtubeSignupRequired"}

RETRYABLE = {ErrorClass.RATE_LIMIT, ErrorClass.SERVER, ErrorClass.NETWORK}

HINTS = {
    ErrorClass.AUTH: "Access token rejected. The client refreshes once; if it still fails, re-run skills/youtube-auth/scripts/authenticate.py.",
    ErrorClass.QUOTA: "YouTube quota is exhausted for today (resets at midnight Pacific Time). Publishing stopped; nothing will be retried.",
    ErrorClass.PERMISSION: "Insufficient permissions: the token lacks a required OAuth scope, or this account does not own the resource. Re-authenticate with the right --scopes profile.",
    ErrorClass.NOT_FOUND: "Resource not found: check the video/caption ID and that it belongs to the authenticated channel.",
    ErrorClass.RATE_LIMIT: "Rate limited by Google; retried with backoff.",
    ErrorClass.SERVER: "Google backend error; retried with exponential backoff.",
    ErrorClass.NETWORK: "Network error or timeout talking to Google.",
    ErrorClass.CLIENT: "The request was rejected as invalid; fix the input and try again.",
    ErrorClass.UNKNOWN: "Unexpected error.",
}


def parse_http_error(exc: Any) -> tuple[int | None, str | None, str]:
    """Extract (status, reason, message) from a googleapiclient HttpError-like object."""
    status = None
    resp = getattr(exc, "resp", None)
    if resp is not None:
        try:
            status = int(getattr(resp, "status", None) or resp.get("status"))
        except (TypeError, ValueError):
            status = None
    reason = None
    message = str(exc)
    content = getattr(exc, "content", None)
    if content:
        try:
            data = json.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
            err = data.get("error", {}) if isinstance(data, dict) else {}
            if isinstance(err, dict):
                message = err.get("message") or message
                errors = err.get("errors") or []
                if errors and isinstance(errors[0], dict):
                    reason = errors[0].get("reason")
                if not reason:
                    for detail in err.get("details") or []:
                        if isinstance(detail, dict) and detail.get("reason"):
                            reason = detail["reason"]
                            break
                if not reason and isinstance(err.get("status"), str):
                    reason = err["status"]
            elif isinstance(err, str):  # OAuth-style {"error": "invalid_grant"}
                reason = err
        except (ValueError, AttributeError):
            pass
    return status, reason, message


def classify(status: int | None, reason: str | None = None) -> ErrorClass:
    if status is None:
        return ErrorClass.NETWORK
    if status == 401:
        return ErrorClass.AUTH
    if status == 403:
        if reason in QUOTA_REASONS:
            return ErrorClass.QUOTA
        if reason in RATE_REASONS:
            return ErrorClass.RATE_LIMIT
        return ErrorClass.PERMISSION
    if status == 404:
        return ErrorClass.NOT_FOUND
    if status == 429:
        return ErrorClass.QUOTA if reason in QUOTA_REASONS else ErrorClass.RATE_LIMIT
    if status in (500, 502, 503, 504):
        return ErrorClass.SERVER
    if 400 <= status < 500:
        return ErrorClass.CLIENT
    return ErrorClass.UNKNOWN


def is_network_error(exc: BaseException) -> bool:
    if isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, socket.gaierror)):
        return True
    try:
        import httplib2

        if isinstance(exc, httplib2.HttpLib2Error):
            return True
    except ImportError:  # pragma: no cover
        pass
    return False


def is_http_error(exc: BaseException) -> bool:
    try:
        from googleapiclient.errors import HttpError
    except ImportError:  # pragma: no cover
        return hasattr(exc, "resp")
    return isinstance(exc, HttpError)


def retry_after_seconds(exc: Any) -> float | None:
    resp = getattr(exc, "resp", None)
    if resp is None:
        return None
    try:
        raw = resp.get("retry-after")
        return float(raw) if raw is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 64.0
    sleep: Callable[[float], None] = time.sleep
    rand: Callable[[], float] = random.random

    def backoff(self, attempt: int) -> float:
        """Full jitter: uniform(0, min(cap, base * 2**attempt)). ``attempt`` starts at 0."""
        ceiling = min(self.max_delay, self.base_delay * (2**attempt))
        return self.rand() * ceiling

    def schedule(self) -> list[float]:
        """Upper bounds of each wait (for display): base*2**n capped."""
        return [min(self.max_delay, self.base_delay * (2**n)) for n in range(self.max_attempts - 1)]

    def run(
        self,
        fn: Callable[[], Any],
        *,
        operation: str,
        endpoint: str = "",
        idempotent: bool = True,
        on_auth_error: Callable[[], bool] | None = None,
        on_quota_error: Callable[[], None] | None = None,
        on_attempt: Callable[[int, Exception | None], None] | None = None,
    ) -> Any:
        """Call ``fn`` with bounded retries.

        ``on_auth_error`` is called once on a 401; returning True means credentials
        were refreshed and one more attempt is allowed.
        """
        log = get_logger()
        refreshed = False
        attempt = 0
        while True:
            try:
                result = fn()
                if on_attempt:
                    on_attempt(attempt, None)
                if attempt:
                    log.info(operation, "succeeded after retry", endpoint=endpoint, retry_count=attempt, result="success")
                return result
            except Exception as exc:  # noqa: BLE001 - classified below, re-raised as APIError
                if on_attempt:
                    on_attempt(attempt, exc)
                if is_http_error(exc):
                    status, reason, message = parse_http_error(exc)
                    cls = classify(status, reason)
                elif is_network_error(exc):
                    status, reason, message, cls = None, type(exc).__name__, str(exc), ErrorClass.NETWORK
                else:
                    raise

                log.warning(
                    operation,
                    message[:300],
                    endpoint=endpoint,
                    http_status=status,
                    error_class=cls.value,
                    reason=reason,
                    retry_count=attempt,
                )

                if cls is ErrorClass.QUOTA:
                    if on_quota_error:
                        on_quota_error()
                    log.error(operation, HINTS[cls], endpoint=endpoint, http_status=status, error_class=cls.value, result="stopped")
                    raise QuotaExceededError(f"{HINTS[cls]} (HTTP {status}, reason={reason})") from exc

                if cls is ErrorClass.AUTH and on_auth_error and not refreshed:
                    refreshed = True
                    if on_auth_error():
                        continue

                retryable = cls in RETRYABLE and (idempotent or cls is not ErrorClass.NETWORK)
                if retryable and attempt + 1 < self.max_attempts:
                    delay = self.backoff(attempt)
                    if cls is ErrorClass.RATE_LIMIT:
                        hinted = retry_after_seconds(exc)
                        if hinted is not None:
                            delay = min(max(delay, hinted), self.max_delay)
                    attempt += 1
                    self.sleep(delay)
                    continue

                log.error(
                    operation,
                    HINTS[cls],
                    endpoint=endpoint,
                    http_status=status,
                    error_class=cls.value,
                    retry_count=attempt,
                    result="failed",
                )
                raise APIError(
                    f"{operation} failed: {message} — {HINTS[cls]}",
                    status=status,
                    reason=reason,
                    classification=cls.value,
                    retryable=cls in RETRYABLE,
                    attempts=attempt + 1,
                ) from exc
