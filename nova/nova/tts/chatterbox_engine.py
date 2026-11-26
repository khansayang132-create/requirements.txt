"""Chatterbox-TTS fine-tuned for Indonesian (grandhigh/Chatterbox-TTS-Indonesian, Apache-2.0):
a neural model that clones a voice from a short reference recording (zero-shot).

Optional and heavy: needs `pip install -r requirements-neural.txt` (PyTorch, ~6 GB) and
downloads ~3.2 GB of weights from Hugging Face on first use. It runs on CPU at about 4-6x slower
than real time. Off unless NOVA_CHATTERBOX=1.

Controls: the director's emotion maps to `exaggeration` (emotional intensity); speed is applied
afterwards with a pitch-preserving time-stretch (ffmpeg atempo), because the model has no speed
control of its own; pitch has no direct control. Output carries Resemble's Perth watermark marking it as AI-generated."""
from __future__ import annotations

import os
import threading

import numpy as np

from .base import Capabilities, Prosody, TTSEngine, TTSUnavailable

REPO = "grandhigh/Chatterbox-TTS-Indonesian"
_lock = threading.Lock()


class ChatterboxEngine(TTSEngine):
    name = "chatterbox-id"
    capabilities = Capabilities(rate=True, volume=True, languages=("id",))
    clones_from_reference = True

    def __init__(self, enabled: bool, device: str = "cpu") -> None:
        self.enabled = enabled
        self.device = device
        self._model = None

    def available(self) -> bool:
        if not self.enabled:
            return False
        # find_spec looks for the package without importing it: importing pulls in PyTorch,
        # which took tens of seconds and froze the status page.
        import importlib.util
        return importlib.util.find_spec("chatterbox") is not None

    def _load(self):
        if not self.available():
            raise TTSUnavailable("Chatterbox is not enabled/installed (NOVA_CHATTERBOX=1 and requirements-neural.txt)")
        with _lock:
            if self._model is None:
                os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # plain HTTPS downloads through proxies
                import torch
                from chatterbox.tts import ChatterboxTTS
                from huggingface_hub import hf_hub_download
                from safetensors.torch import load_file
                torch.set_num_threads(max(1, os.cpu_count() or 1))
                model = ChatterboxTTS.from_pretrained(device=self.device)
                model.t3.load_state_dict(load_file(hf_hub_download(REPO, "t3_cfg.safetensors"), device="cpu"))
                self._model = model
        return self._model

    def voices(self) -> list[dict]:
        return [{"id": "default", "language": "id"}, {"id": "<reference wav>", "language": "id"}] if self.available() else []

    def synthesize(self, text: str, language: str, prosody: Prosody, voice: str | None = None) -> tuple[np.ndarray, int]:
        model = self._load()
        import torch
        # Emotion intensity: the director's intonation range is the best proxy (excited > 1, sad < 1).
        exaggeration = float(np.clip(0.5 * prosody.pitch_range, 0.25, 0.9))
        cfg_weight = 0.5  # Chatterbox's default; pace is set afterwards by a real time-stretch
        ref = voice if voice and os.path.isfile(voice) else None
        torch.manual_seed(1234)  # same text + settings -> same take
        with _lock, torch.inference_mode():
            wav = model.generate(text, audio_prompt_path=ref, exaggeration=exaggeration,
                                 cfg_weight=cfg_weight, temperature=0.7)
        x = wav.squeeze(0).cpu().numpy().astype(np.float64)
        if abs(prosody.rate - 1.0) > 0.01:  # the model has no speed control: stretch without changing pitch
            from ..audio import time_stretch
            x = time_stretch(x, int(model.sr), prosody.rate)
        if prosody.volume_db:
            x = x * 10 ** (prosody.volume_db / 20)
        return x, int(model.sr)
