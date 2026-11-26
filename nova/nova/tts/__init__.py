from __future__ import annotations

from ..config import Settings
from .base import Capabilities, Prosody, TTSEngine, TTSUnavailable
from .espeak import EspeakEngine
from .piper_engine import PiperEngine
from .sherpa_engine import SherpaEngine

__all__ = ["Capabilities", "Prosody", "TTSEngine", "TTSUnavailable", "engines", "get_engine"]


def engines(settings: Settings) -> dict[str, TTSEngine]:
    return {
        "espeak-ng": EspeakEngine(),
        "piper": PiperEngine(settings.piper_model),
        "sherpa-onnx": SherpaEngine(settings.sherpa_model_dir),
    }


def get_engine(settings: Settings, name: str | None) -> TTSEngine:
    all_engines = engines(settings)
    if name:
        if name not in all_engines:
            raise TTSUnavailable(f"unknown engine {name!r}")
        engine = all_engines[name]
        if not engine.available():
            raise TTSUnavailable(f"engine {name!r} is not available on this machine")
        return engine
    for preferred in ("piper", "sherpa-onnx", "espeak-ng"):
        if all_engines[preferred].available():
            return all_engines[preferred]
    raise TTSUnavailable("no TTS engine is available: install espeak-ng or configure a Piper/Sherpa model")
