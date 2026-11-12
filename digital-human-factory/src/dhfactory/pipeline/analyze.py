"""STEP 1: split a script into scenes (sentences grouped to ~12 words), with a speaking-time estimate."""

from __future__ import annotations

import re

from ..state import SceneSpec

WPS = 2.6   # relaxed presenter pace, words per second


def split_scenes(script: str, max_words: int = 14) -> list[SceneSpec]:
    text = re.sub(r"\s+", " ", script).strip()
    if not text:
        raise ValueError("script is empty")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    scenes, buf = [], []
    for s in sentences:
        if buf and len(" ".join(buf + [s]).split()) > max_words:
            scenes.append(" ".join(buf))
            buf = []
        buf.append(s)
    if buf:
        scenes.append(" ".join(buf))
    return [SceneSpec(index=i, text=t, words=len(t.split()), est_seconds=round(len(t.split()) / WPS, 2)) for i, t in enumerate(scenes)]
