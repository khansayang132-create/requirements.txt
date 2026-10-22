"""Thin, checked wrappers around ffmpeg / ffprobe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    pass


def run_ffmpeg(args: list[str]) -> str:
    """Run ffmpeg with fixed flags; raise MediaError with the tail of stderr on failure."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise MediaError("ffmpeg failed: " + p.stderr.strip()[-1500:])
    return p.stderr


def ffprobe(path: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise MediaError(f"ffprobe could not read {path}: {p.stderr.strip()[-500:]}")
    return json.loads(p.stdout)


def probe_duration(path: Path) -> float:
    return float(ffprobe(path)["format"].get("duration", 0) or 0)
