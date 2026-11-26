"""Engine interface. The director produces a `Prosody` per sentence; each engine maps it onto the
controls it really has and reports which ones it honoured, so nothing is silently ignored."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


class TTSUnavailable(RuntimeError):
    """The engine or its model is not installed. Never fall back to fake audio."""


@dataclass
class Prosody:
    rate: float = 1.0           # 1.0 = engine default speed
    pitch_semitones: float = 0.0
    pitch_range: float = 1.0    # multiplier on intonation range
    volume_db: float = 0.0
    emphasis: list[str] = field(default_factory=list)


@dataclass
class Capabilities:
    rate: bool = False
    pitch: bool = False
    pitch_range: bool = False
    volume: bool = False
    emphasis: bool = False
    languages: tuple[str, ...] = ()


class TTSEngine:
    name = "base"
    capabilities = Capabilities()
    clones_from_reference = False  # True: `voice` may be a reference WAV path to clone (neural engines)

    def available(self) -> bool:
        return False

    def voices(self) -> list[dict]:
        return []

    def synthesize(self, text: str, language: str, prosody: Prosody, voice: str | None = None) -> tuple[np.ndarray, int]:
        raise NotImplementedError

    def info(self) -> dict:
        c = self.capabilities
        return {
            "name": self.name,
            "available": self.available(),
            "controls": {k: getattr(c, k) for k in ("rate", "pitch", "pitch_range", "volume", "emphasis")},
            "languages": list(c.languages),
        }
