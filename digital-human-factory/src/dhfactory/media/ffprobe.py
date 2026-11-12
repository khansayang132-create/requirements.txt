from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .ffmpeg import binary


def probe(path: Path) -> dict:
    proc = subprocess.run([binary("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                          check=False, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr[-300:]}")
    return json.loads(proc.stdout)


def decode_errors(path: Path) -> str:
    """Fully decode the file; any stderr output means a decode problem."""
    proc = subprocess.run([binary(), "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"], check=False, capture_output=True, text=True, timeout=600)
    return proc.stderr.strip()
