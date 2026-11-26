"""Sherpa-ONNX offline TTS (VITS / Matcha / Kokoro model folders). Used only when
NOVA_SHERPA_MODEL_DIR holds model.onnx + tokens.txt (and espeak-ng-data for VITS-piper models)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import Capabilities, Prosody, TTSEngine, TTSUnavailable


class SherpaEngine(TTSEngine):
    name = "sherpa-onnx"
    capabilities = Capabilities(rate=True, languages=())

    def __init__(self, model_dir: str) -> None:
        self.model_dir = Path(model_dir) if model_dir else None
        self._tts = None

    def _model_file(self) -> Path | None:
        if not self.model_dir or not self.model_dir.is_dir():
            return None
        onnx = sorted(self.model_dir.glob("*.onnx"))
        return onnx[0] if onnx and (self.model_dir / "tokens.txt").is_file() else None

    def available(self) -> bool:
        if self._model_file() is None:
            return False
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        if self._tts is None:
            if not self.available():
                raise TTSUnavailable("Sherpa-ONNX model not configured (set NOVA_SHERPA_MODEL_DIR)")
            import sherpa_onnx
            d = self.model_dir
            data_dir = d / "espeak-ng-data"
            vits = sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(self._model_file()), tokens=str(d / "tokens.txt"),
                data_dir=str(data_dir) if data_dir.is_dir() else "",
                lexicon=str(d / "lexicon.txt") if (d / "lexicon.txt").is_file() else "")
            cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=2))
            self._tts = sherpa_onnx.OfflineTts(cfg)
        return self._tts

    def voices(self) -> list[dict]:
        return [{"id": self.model_dir.name, "language": "model"}] if self.available() else []

    def synthesize(self, text: str, language: str, prosody: Prosody, voice: str | None = None) -> tuple[np.ndarray, int]:
        tts = self._load()
        audio = tts.generate(text, sid=int(voice) if voice and voice.isdigit() else 0, speed=float(prosody.rate))
        return np.asarray(audio.samples, dtype=np.float64), int(audio.sample_rate)
