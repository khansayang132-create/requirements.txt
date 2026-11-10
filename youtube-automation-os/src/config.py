"""Configuration: ``config/settings.yaml`` + ``config/scopes.yaml`` + environment (``.env``).

Precedence: CLI flag > environment variable > settings.yaml > built-in default.
Secrets (client secret, tokens) are read only from the environment or the token file,
never from YAML.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigError

_ROOT = Path(__file__).resolve().parents[1]


def project_root() -> Path:
    """Toolkit root (the folder that holds ``src/`` and ``skills/``). Override: YTAOS_ROOT."""
    return Path(os.getenv("YTAOS_ROOT") or _ROOT)


def load_env() -> None:
    """Load ``<root>/.env`` if python-dotenv is installed. Existing env vars win."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a pinned dependency
        return
    load_dotenv(project_root() / ".env", override=False)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing config file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def load_settings(path: Path | None = None) -> dict:
    return _read_yaml(path or project_root() / "config" / "settings.yaml")


def load_scopes(path: Path | None = None) -> dict:
    return _read_yaml(path or project_root() / "config" / "scopes.yaml")


def load_yaml_file(path: str | Path) -> dict:
    """Read a user-supplied YAML (or JSON, which is valid YAML) file."""
    return _read_yaml(Path(path))


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def dry_run_locked() -> bool:
    """True when ``YOUTUBE_DRY_RUN`` is truthy: real destructive calls are refused even with --confirm.

    Unset counts as unlocked so tests and fresh installs behave like the CLI flags say;
    ``.env.example`` ships with the lock ON.
    """
    return env_bool("YOUTUBE_DRY_RUN", default=False)


def upload_defaults(settings: dict) -> dict:
    """``defaults`` from settings.yaml with YOUTUBE_DEFAULT_PRIVACY / _CATEGORY env overrides."""
    d = dict(settings.get("defaults") or {})
    if os.getenv("YOUTUBE_DEFAULT_PRIVACY"):
        d["privacy"] = os.environ["YOUTUBE_DEFAULT_PRIVACY"].strip()
    if os.getenv("YOUTUBE_DEFAULT_CATEGORY"):
        d["category_id"] = os.environ["YOUTUBE_DEFAULT_CATEGORY"].strip()
    d.setdefault("privacy", "private")
    d.setdefault("category_id", "22")
    d.setdefault("made_for_kids", False)
    return d


def resolve_path(value: str | Path) -> Path:
    """Relative paths in configs are relative to the toolkit root."""
    p = Path(value).expanduser()
    return p if p.is_absolute() else project_root() / p


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get(settings: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = settings
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
