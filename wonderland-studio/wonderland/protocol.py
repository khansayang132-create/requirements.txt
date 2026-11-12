"""How the departments talk to the CEO agent.

Every piece of work ends in one ``AgentReport`` with exactly the fields of the company
protocol::

    {"agent": "", "task_id": "", "status": "", "output": {}, "evidence": [], "errors": [], "next_action": ""}

``status`` is one of success / failed / blocked / skipped. A report is stored verbatim in the
database, so "done" always has a record of what was produced and the evidence for it. A
department never reports success for work it did not do: a handler either returns a report
built from real results or raises one of the errors below.

Errors carry their class, because the queue treats them differently:

  TransientError   try again later with backoff (network, rate limit, busy encoder)
  PermanentError   retrying cannot help (bad input, rule violation); fail now, tell the owner
  BlockedError     needs something only a person can provide (sign-in, approval, budget);
                   parked without burning retries, re-checked every cycle
"""

from __future__ import annotations

from dataclasses import dataclass, field

STATUSES = ("success", "failed", "blocked", "skipped")
ERROR_CLASSES = ("transient", "permanent", "blocked", "unknown")


@dataclass
class AgentReport:
    agent: str
    task_id: str
    status: str
    output: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    next_action: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")
        if self.status == "success" and self.errors:
            raise ValueError("a successful report cannot carry errors")
        if self.status == "failed" and not self.errors:
            raise ValueError("a failed report must say what failed")

    def as_dict(self) -> dict:
        return {"agent": self.agent, "task_id": str(self.task_id), "status": self.status, "output": self.output,
                "evidence": self.evidence, "errors": self.errors, "next_action": self.next_action}


class StudioError(Exception):
    error_class = "permanent"


class TransientError(StudioError):
    error_class = "transient"


class PermanentError(StudioError):
    error_class = "permanent"


class QualityError(PermanentError):
    """The episode failed quality control; the CEO may order a new story instead of a retry."""


class BlockedError(StudioError):
    """Work that cannot continue without a person. ``needs`` says exactly what is missing."""

    error_class = "blocked"

    def __init__(self, message: str, needs: str = "") -> None:
        super().__init__(message)
        self.needs = needs or message


def classify(exc: BaseException) -> str:
    """Error class for any exception a department can raise."""
    if isinstance(exc, StudioError):
        return exc.error_class
    if getattr(exc, "transient", False) is True:          # e.g. audio.tts.TTSError(transient=True)
        return "transient"
    if isinstance(exc, (TimeoutError, ConnectionError, InterruptedError)):
        return "transient"
    if isinstance(exc, (ValueError, KeyError, TypeError, AssertionError, FileNotFoundError, PermissionError)):
        return "permanent"
    return "unknown"                                       # retried once, then treated as permanent
