"""Exception hierarchy. Every error a CLI can show the user is one of these.

Messages never contain token values: callers pass identifiers and statuses, not secrets.
"""

from __future__ import annotations


class YTAOSError(Exception):
    """Base class. ``exit_code`` is what CLIs return when this error stops them."""

    exit_code = 1


class ConfigError(YTAOSError):
    """Missing or invalid configuration (env vars, YAML files)."""

    exit_code = 3


class AuthError(YTAOSError):
    """No usable OAuth credentials (missing token, revoked refresh token, wrong scopes)."""

    exit_code = 4


class ScopeError(AuthError):
    """The stored token lacks scopes required for the requested operation."""

    def __init__(self, missing: list[str]):
        self.missing = sorted(missing)
        super().__init__(
            "The saved token is missing required OAuth scopes: "
            + ", ".join(self.missing)
            + ". Re-run authenticate.py with the needed --scopes profile."
        )


class ValidationError(YTAOSError):
    """Input failed validation. ``issues`` lists every problem, not just the first."""

    exit_code = 5

    def __init__(self, message: str, issues: list[str] | None = None):
        self.issues = list(issues or [])
        detail = ("\n  - " + "\n  - ".join(self.issues)) if self.issues else ""
        super().__init__(message + detail)


class ConfirmationRequired(YTAOSError):
    """A destructive action was requested without --confirm (or while the dry-run lock is on)."""

    exit_code = 2


class QuotaExceededError(YTAOSError):
    """The estimated or actual YouTube quota is exhausted. Never retried automatically."""

    exit_code = 6


class DuplicateUploadError(YTAOSError):
    """The same video file was already uploaded (or may have been). Refuses to upload again."""

    exit_code = 7


class UploadUncertainError(YTAOSError):
    """An upload may or may not have completed remotely; a human must check before retrying."""

    exit_code = 8


class DependencyMissing(YTAOSError):
    """An optional dependency (e.g. Whisper) is not installed."""

    exit_code = 9


class APIError(YTAOSError):
    """A Google API call failed after classification and any retries.

    ``classification`` is one of the values in ``retry.ErrorClass``.
    """

    exit_code = 10

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        reason: str | None = None,
        classification: str = "unknown",
        retryable: bool = False,
        attempts: int = 1,
    ):
        self.status = status
        self.reason = reason
        self.classification = classification
        self.retryable = retryable
        self.attempts = attempts
        super().__init__(message)
