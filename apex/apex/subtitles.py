"""SRT subtitles timed to each scene's narration."""
from __future__ import annotations

import re

from .models import Storyboard

MAX_WORDS_PER_CUE = 6


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(board: Storyboard, narration_seconds: list[float]) -> str:
    """Split each scene's narration into short cues spread over the spoken part of the scene."""
    cues, idx = [], 1
    for scene, spoken in zip(board.scenes, narration_seconds):
        words = scene.subtitle_text.split()
        if not words:
            continue
        chunks = [words[i:i + MAX_WORDS_PER_CUE] for i in range(0, len(words), MAX_WORDS_PER_CUE)]
        t = scene.start_time
        per_word = spoken / len(words)
        for ch in chunks:
            end = min(scene.end_time, t + per_word * len(ch))
            cues.append(f"{idx}\n{_ts(t)} --> {_ts(end)}\n{' '.join(ch)}\n")
            idx += 1
            t = end
    return "\n".join(cues)


_CUE = re.compile(r"(\d+)\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.+)", re.S)


def validate_srt(text: str) -> list[str]:
    """Return syntax/timing problems; empty means valid."""
    problems, last_end, expected = [], -1.0, 1
    blocks = [b for b in text.strip().split("\n\n") if b.strip()]
    if not blocks:
        return ["no cues"]
    for b in blocks:
        m = _CUE.fullmatch(b.strip())
        if not m:
            problems.append(f"malformed cue: {b[:40]!r}")
            continue
        g = list(map(int, m.groups()[:9]))
        start = g[1] * 3600 + g[2] * 60 + g[3] + g[4] / 1000
        end = g[5] * 3600 + g[6] * 60 + g[7] + g[8] / 1000
        if g[0] != expected:
            problems.append(f"cue {g[0]} out of sequence (expected {expected})")
        if end <= start:
            problems.append(f"cue {g[0]} ends before it starts")
        if start < last_end - 1e-3:
            problems.append(f"cue {g[0]} overlaps the previous cue")
        last_end, expected = end, expected + 1
    return problems


def build_title_srt(board: Storyboard) -> str:
    """One headline cue per scene (the script's on-screen text), shown for the whole scene."""
    cues, idx = [], 1
    for scene in board.scenes:
        if scene.on_screen_text.strip():
            cues.append(f"{idx}\n{_ts(scene.start_time + 0.1)} --> {_ts(scene.end_time - 0.05)}\n"
                        f"{scene.on_screen_text.strip()}\n")
            idx += 1
    return "\n".join(cues)
