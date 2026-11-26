from __future__ import annotations

from ..config import Settings
from .base import Capabilities, Prosody, TTSEngine, TTSUnavailable
from .chatterbox_engine import ChatterboxEngine
from .espeak import EspeakEngine
from .piper_engine import PiperEngine
from .sherpa_engine import SherpaEngine

__all__ = ["Capabilities", "Prosody", "TTSEngine", "TTSUnavailable", "engines", "get_engine"]


def engines(settings: Settings) -> dict[str, TTSEngine]:
    return {
        "chatterbox-id": _chatterbox(settings),
        "espeak-ng": EspeakEngine(),
        "piper": PiperEngine(settings.piper_model),
        "sherpa-onnx": SherpaEngine(settings.sherpa_model_dir),
    }


def get_engine(settings: Settings, name: str | None, has_reference: bool = True) -> TTSEngine:
    """Pick an engine. A neural cloning engine is chosen automatically only when there is a
    reference recording to clone; without one it would fall back to its own default voice."""
    all_engines = engines(settings)
    if name:
        if name not in all_engines:
            raise TTSUnavailable(f"unknown engine {name!r}")
        engine = all_engines[name]
        if not engine.available():
            raise TTSUnavailable(f"engine {name!r} is not available on this machine")
        return engine
    for preferred in ("chatterbox-id", "piper", "sherpa-onnx", "espeak-ng"):
        engine = all_engines[preferred]
        if engine.clones_from_reference and not has_reference:
            continue
        if engine.available():
            return all_engines[preferred]
    raise TTSUnavailable("no TTS engine is available: install espeak-ng or configure a Piper/Sherpa model")


_CHATTERBOX: dict[bool, ChatterboxEngine] = {}


def _chatterbox(settings: Settings) -> ChatterboxEngine:
    # One instance per process: the model is ~3 GB and takes over a minute to load.
    if settings.chatterbox not in _CHATTERBOX:
        _CHATTERBOX[settings.chatterbox] = ChatterboxEngine(settings.chatterbox)
    return _CHATTERBOX[settings.chatterbox]
