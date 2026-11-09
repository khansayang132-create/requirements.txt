"""Shared plumbing for the skill scripts: env + settings loading, client construction,
JSON output and uniform error handling / exit codes.

Exit codes: 0 ok · 1 generic · 2 confirmation required · 3 config · 4 auth ·
5 validation · 6 quota · 7 duplicate · 8 upload uncertain · 9 missing optional
dependency · 10 API error · 11 job locked · 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import get, load_env, load_settings, resolve_path
from .exceptions import YTAOSError
from .logger import get_logger, new_request_id
from .quota_manager import QuotaManager, from_settings
from .retry import RetryPolicy
from .state import StateStore


@dataclass
class Runtime:
    settings: dict
    state_dir: Path
    store: StateStore
    quota: QuotaManager
    policy: RetryPolicy
    request_id: str


def runtime(settings: dict | None = None) -> Runtime:
    load_env()
    settings = settings or load_settings()
    state_dir = resolve_path(os.getenv("YTAOS_STATE_DIR") or get(settings, "paths.state_dir", "state"))
    retry = get(settings, "retry", {}) or {}
    policy = RetryPolicy(
        max_attempts=int(retry.get("max_attempts", 5)),
        base_delay=float(retry.get("base_delay_seconds", 1.0)),
        max_delay=float(retry.get("max_delay_seconds", 64.0)),
    )
    return Runtime(settings, state_dir, StateStore(state_dir), from_settings(settings, state_dir), policy, new_request_id())


def make_client(rt: Runtime, operations: list[str]):
    from .oauth_manager import load_credentials
    from .youtube_client import YouTubeClient

    creds = load_credentials(operations)
    return YouTubeClient.from_credentials(creds, quota=rt.quota, policy=rt.policy)


def add_safety_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Preview only; makes no write calls. Wins over --confirm.")
    parser.add_argument("--confirm", action="store_true", help="Required to perform a real write on YouTube.")


def add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout.")


def emit(data: Any, as_json: bool, human: Callable[[Any], str] | None = None) -> None:
    if as_json or human is None:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(human(data))


def run(main: Callable[[], int | None]) -> None:
    """Run a script's main(); map known errors to exit codes without tracebacks."""
    try:
        code = main()
    except YTAOSError as exc:
        get_logger().error(type(exc).__name__, str(exc)[:500], result="failed")
        print(f"\nERROR ({type(exc).__name__}): {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted. State was saved; re-run the same command to resume.", file=sys.stderr)
        sys.exit(130)
    sys.exit(code or 0)
