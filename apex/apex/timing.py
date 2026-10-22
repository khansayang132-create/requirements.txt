"""Narration timing: estimates before TTS, exact allocation after TTS."""
from __future__ import annotations

import re

# Speaking rates in words per second at the voice speed the pipeline uses.
# Indonesian words are longer on average than English ones.
WORDS_PER_SECOND = {"id": 2.3, "en": 2.6}

SCENE_PAD_SECONDS = 0.45   # breathing room after each narration line
MIN_SCENE_SECONDS = 2.0    # long enough for a visual to register


def word_count(text: str) -> int:
    return len(re.findall(r"[\w'’-]+", text, flags=re.UNICODE))


def estimate_seconds(text: str, language: str) -> float:
    """Rough narration length before any audio exists (used by script review)."""
    return word_count(text) / WORDS_PER_SECOND[language]


def scene_seconds(narration_audio_seconds: float) -> float:
    """Scene length from the measured narration clip length."""
    return max(MIN_SCENE_SECONDS, narration_audio_seconds + SCENE_PAD_SECONDS)


def allocate(narration_seconds: list[float], fps: int = 1000) -> list[tuple[float, float, float]]:
    """(start, end, duration) per scene, contiguous from 0; durations snap to whole frames."""
    out, t = [], 0.0
    for n in narration_seconds:
        d = round(max(1, round(scene_seconds(n) * fps)) / fps, 3)
        out.append((round(t, 3), round(t + d, 3), d))
        t = round(t + d, 3)
    return out


def fits_target(total: float, target: float, tolerance: float) -> bool:
    return abs(total - target) <= tolerance
