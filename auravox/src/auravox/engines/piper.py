"""Piper adapter (neural, local, CPU). Engine: piper-tts (GPL-3.0, OHF-Voice/piper1-gpl). Voices: separate .onnx
models whose licences differ per voice (see the model registry). A voice must be installed by the model manager
first; there is no silent download here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import SR, Engine, EngineError, MissingModel, Synth, Unsupported, resample


PEAK = 10 ** (-1 / 20)


class PiperEngine(Engine):
    name = "piper"
    license = "GPL-3.0 (piper-tts 1.x runtime); each voice model has its own licence"
    quality_rank = 50
    offline = True

    def __init__(self, store):
        self.store = store                     # ModelStore
        self._cache: dict[str, object] = {}

    def installed(self) -> list[dict]:
        return [m for m in self.store.installed("piper")]

    def capabilities(self) -> dict:
        ms = self.installed()
        langs = sorted({m["meta"].get("lang_code", "?") for m in ms})
        return {"languages": langs, "voices": [m["key"] for m in ms], "emotion": "rate/noise only (length_scale, noise_scale)",
                "ssml": False, "phoneme_timing": True, "speakers": sum(int(m["meta"].get("num_speakers", 1)) for m in ms),
                "commercial_use": "check model licence", "voice_cloning": False, "speech_to_speech": False}

    def health(self) -> tuple[str, str]:
        try:
            import piper  # noqa: F401
        except ImportError:
            return "BLOCKED", "piper-tts not installed (pip install piper-tts)"
        ms = self.installed()
        if not ms:
            return "BLOCKED", "piper-tts installed, but no voice model is installed (avx models install <key>; needs huggingface.co)"
        try:
            s = self.synthesize("test", {"model": ms[0]["key"]}, {})
            return ("PASS", f"spoke with {ms[0]['key']} ({len(s.audio) / SR:.2f}s)") if float(np.abs(s.audio).max()) > 0.05 else (
                "FAIL", "silent output")
        except Exception as e:  # noqa: BLE001
            return "FAIL", f"{type(e).__name__}: {e}"

    def _voice(self, key: str):
        if key in self._cache:
            return self._cache[key]
        m = self.store.get(key)
        if not m or m["status"] != "PASS" or not Path(m["path"]).is_file():
            raise MissingModel(f"Piper voice {key} is not installed")
        from piper import PiperVoice
        try:
            v = PiperVoice.load(m["path"], config_path=m.get("config_path"), include_alignments=True)
        except TypeError:
            v = PiperVoice.load(m["path"], config_path=m.get("config_path"))
        self._cache[key] = v
        return v

    def synthesize(self, text: str, voice: dict, controls: dict) -> Synth:
        key = voice.get("model")
        if not key:
            raise Unsupported("Piper needs a voice model key")
        v = self._voice(key)
        from piper import SynthesisConfig
        cfg = SynthesisConfig(speaker_id=voice.get("speaker_id"), length_scale=voice.get("length_scale", 1.0) * 100 / controls.get("rate_pct", 100),
                              noise_scale=voice.get("noise_scale", 0.667) * controls.get("range_mul", 1.0), noise_w_scale=voice.get("noise_w", 0.8),
                              volume=min(1.0, controls.get("volume_pct", 100) / 100))
        chunks, ph, t = [], [], 0.0
        try:
            gen = v.synthesize(text, cfg, include_alignments=True)
        except TypeError:
            gen = v.synthesize(text, cfg)
        sr = SR
        for ch in gen:
            sr = ch.sample_rate
            a = ch.audio_float_array
            al = getattr(ch, "phoneme_alignments", None)
            if al:
                for item in al:
                    n = getattr(item, "num_samples", None)
                    sym = getattr(item, "phoneme", "")
                    if n:
                        ph.append((round(t, 3), round(t + n / sr, 3), sym))
                        t += n / sr
            else:
                t += len(a) / sr
            chunks.append(a)
        if not chunks:
            raise EngineError("Piper returned no audio")
        x = resample(np.concatenate(chunks).astype(np.float32), sr, SR)
        peak = float(np.abs(x).max())
        if peak > PEAK:                                       # Piper normalises to full scale; keep 1 dB of headroom
            x *= PEAK / peak
        pre = int(controls.get("pause_before", 0) * SR)
        post = int(controls.get("pause_after", 0) * SR)
        x = np.concatenate([np.zeros(pre, np.float32), x, np.zeros(post, np.float32)])
        ph = [(a + pre / SR, b + pre / SR, s) for a, b, s in ph]
        return Synth(x, ph or None, "engine" if ph else "none", {"model": key, "native_rate": sr})
