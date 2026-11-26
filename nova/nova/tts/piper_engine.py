"""Piper (neural VITS, ONNX). Used only when NOVA_PIPER_MODEL points at a .onnx voice with its
.onnx.json next to it. Rate maps to Piper's length_scale; pitch and volume are applied after
synthesis by the voice-conversion and mastering stages, and the report says so."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import Capabilities, Prosody, TTSEngine, TTSUnavailable


class PiperEngine(TTSEngine):
    name = "piper"
    capabilities = Capabilities(rate=True, volume=True, languages=())

    def __init__(self, model_path: str) -> None:
        self.model_path = Path(model_path) if model_path else None
        self._voice = None

    def available(self) -> bool:
        if not self.model_path or not self.model_path.is_file():
            return False
        try:
            import piper  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._voice is None:
            if not self.available():
                raise TTSUnavailable("Piper model not configured (set NOVA_PIPER_MODEL to a .onnx voice)")
            from piper import PiperVoice
            self._voice = PiperVoice.load(str(self.model_path))
        return self._voice

    def voices(self) -> list[dict]:
        return [{"id": self.model_path.stem, "language": "model"}] if self.available() else []

    def synthesize(self, text: str, language: str, prosody: Prosody, voice: str | None = None) -> tuple[np.ndarray, int]:
        v = self._load()
        from piper import SynthesisConfig
        cfg = SynthesisConfig(length_scale=1.0 / max(prosody.rate, 0.3),
                              volume=float(10 ** (prosody.volume_db / 20)))
        chunks = [c.audio_float_array for c in v.synthesize(text, syn_config=cfg)]
        if not chunks:
            raise TTSUnavailable("Piper produced no audio")
        return np.concatenate(chunks).astype(np.float64), int(v.config.sample_rate)
