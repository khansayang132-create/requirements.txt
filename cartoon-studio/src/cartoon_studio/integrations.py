"""Evidence-based host integration checks; never mutates Codex settings."""
from __future__ import annotations
import importlib.util
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _version(command: str, args: list[str]) -> tuple[bool, str]:
    path = shutil.which(command)
    if not path:
        return False, f"{command} not found on PATH"
    try:
        p = subprocess.run([path, *args], capture_output=True, text=True, timeout=8)
        line = (p.stdout or p.stderr).strip().splitlines()
        return p.returncode == 0, line[0] if line else f"exit={p.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"probe failed: {type(exc).__name__}"


def integration_report(root: Path | None = None) -> dict[str, Any]:
    root = (root or Path.cwd()).resolve()
    system = platform.system()
    codex_ok, codex_detail = _version("codex", ["--version"])
    claude_ok, claude_detail = _version("claude", ["--version"])
    voice_supported = system in {"Darwin", "Windows"}
    voice_status = "NOT_TESTED" if voice_supported else "BLOCKED"
    voice_detail = (
        f"{system}: compatible platform; setup still requires the installed Voice Notify plugin, Codex >=0.145.0, user hook trust, and audible test"
        if voice_supported else f"{system}: Voice Notify setup skill documents macOS/Windows only"
    )
    empire_docs = (root / "documentation/integrations/empire-llm-codex.md").is_file()
    # Never inspect credentials or invoke a paid route from this diagnostic.
    empire_status = "NOT_TESTED" if empire_docs else "BLOCKED"
    empire_detail = "Local Empire runner/keyring not probed; no credential values inspected and no model request sent" if empire_docs else "Empire integration guide missing"
    workflows = (root / "AGENTS.md").is_file() and (root / ".codex/agents").is_dir()
    result = {
        "schema_version": 1,
        "host": {"os": system, "python": platform.python_version()},
        "integrations": [
            {"name": "Codex CLI", "status": "PASS" if codex_ok else "BLOCKED", "detail": codex_detail},
            {"name": "Claude Code CLI", "status": "PASS" if claude_ok else "BLOCKED", "detail": claude_detail},
            {"name": "Codex Dev Workflows project contract", "status": "PASS" if workflows else "FAIL", "detail": "AGENTS.md and .codex/agents found" if workflows else "Project contract or agent definitions missing"},
            {"name": "Voice Notify for Codex", "status": voice_status, "detail": voice_detail},
            {"name": "Empire LLM for Codex", "status": empire_status, "detail": empire_detail},
        ],
        "safety": {"credentials_read": False, "external_model_calls": 0, "paid_calls": 0, "settings_mutated": False},
    }
    return result
