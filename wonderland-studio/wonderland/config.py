"""Configuration: the two YAML files plus a few environment overrides. No secrets live here.

``universe.yaml`` is the creative bible (characters, world, brand); ``studio.yaml`` is how the
company operates (slots, schedule, quality limits, publishing mode, budget).

Environment overrides (all optional):
  WONDERLAND_STATE_DIR      where the database, episodes, caches and logs live
  WONDERLAND_PUBLISH_MODE   off | review | auto   (overrides publishing.mode)
  WONDERLAND_RENDER_BACKEND auto | three | flat   (overrides video.backend)
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PUBLISH_MODES = ("off", "review", "auto")


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def load_universe(root: Path = ROOT) -> dict:
    return load_yaml(Path(root) / "config" / "universe.yaml")


def load_studio(root: Path = ROOT) -> dict:
    cfg = load_yaml(Path(root) / "config" / "studio.yaml")
    mode = os.environ.get("WONDERLAND_PUBLISH_MODE")
    if mode:
        cfg.setdefault("publishing", {})["mode"] = mode
    if cfg.get("publishing", {}).get("mode", "off") not in PUBLISH_MODES:
        raise ValueError(f"publishing.mode must be one of {PUBLISH_MODES}")
    backend = os.environ.get("WONDERLAND_RENDER_BACKEND")
    if backend:
        cfg.setdefault("video", {})["backend"] = backend
    cfg["_root"] = str(root)
    return cfg


def state_dir(cfg: dict) -> Path:
    override = os.environ.get("WONDERLAND_STATE_DIR")
    if override:
        path = Path(override)
    else:
        path = Path(cfg.get("paths", {}).get("state_dir", "state"))
        if not path.is_absolute():
            path = Path(cfg.get("_root", ROOT)) / path
    path.mkdir(parents=True, exist_ok=True)
    return path
