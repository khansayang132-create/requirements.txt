"""The one confirmation gate for every destructive action (upload, update, delete,
publish, privacy change, thumbnail/caption writes).

Rules, in order:
1. ``--dry-run`` given → dry run (even if ``--confirm`` is also given).
2. ``--confirm`` not given → refuse with an explanation (exit code 2).
3. ``YOUTUBE_DRY_RUN`` env lock is on → refuse even with ``--confirm``.
4. otherwise → execute.
"""

from __future__ import annotations

from .config import dry_run_locked
from .exceptions import ConfirmationRequired

DRY_RUN = "dry_run"
EXECUTE = "execute"


def decide_mode(*, dry_run: bool, confirm: bool, action: str) -> str:
    if dry_run:
        return DRY_RUN
    if not confirm:
        raise ConfirmationRequired(
            f"Refusing to {action}: this changes your YouTube channel. "
            "Re-run with --dry-run to preview, or --confirm to execute."
        )
    if dry_run_locked():
        raise ConfirmationRequired(
            f"Refusing to {action}: YOUTUBE_DRY_RUN is enabled (safety lock). "
            "Set YOUTUBE_DRY_RUN=false in .env to allow real API writes, then re-run with --confirm."
        )
    return EXECUTE
