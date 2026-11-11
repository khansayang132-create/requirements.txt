"""Voice engines behind one interface.

Providers (tried in the order given in studio.yaml → audio.voice_providers):

* ``kokoro``     Kokoro-82M via kokoro-onnx. Free, neural, Apache-2.0 model. Needs the model
                 files (``python -m wonderland voices install``). The production default.
* ``espeak``     eSpeak NG. Free, formant (robotic but clear). Always available through the
                 pip package ``espeakng-loader`` or an ``espeak-ng`` binary. The fallback.
* ``elevenlabs`` Paid API. Used only when ELEVENLABS_API_KEY is set AND the owner has set
                 budget.paid_providers_authorized: true. Costs are recorded per character.

A provider that is not installed/configured raises ``TTSUnavailable``; nothing ever
falls back to silence or to a fake clip. Every clip is cached by (provider, voice
profile, text), so a restart or a re-render does not synthesize (or pay) twice.

A character's voice is a *profile* from config/universe.yaml: provider-specific voice
name plus speed and pitch. Pitch for neural voices is done by resampling (generate
slower, play faster), which keeps the tempo and raises the tone a little — enough to
tell the five friends apart while staying natural.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

SR = 44100


class TTSUnavailable(RuntimeError):
    pass


class TTSError(RuntimeError):
    """Synthesis failed for this text (retryable depending on ``transient``)."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def clean_text(text: str) -> str:
    text = re.sub(r"[^\w\s.,!?'\-:;]", " ", text, flags=re.UNICODE)
    text = text.replace("&", " and ")
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x.astype(np.float32)
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def trim_silence(x: np.ndarray, sr: int = SR, threshold: float = 0.012, pad: float = 0.04) -> np.ndarray:
    if len(x) == 0:
        return x
    loud = np.where(np.abs(x) > threshold)[0]
    if len(loud) == 0:
        return x[:0]
    a = max(0, loud[0] - int(pad * sr))
    b = min(len(x), loud[-1] + int(pad * sr))
    return x[a:b]


def polish(x: np.ndarray, sr: int = SR, target_rms: float = 0.11) -> np.ndarray:
    """Trim, level and fade a raw voice clip."""
    x = trim_silence(x.astype(np.float32), sr)
    if len(x) < sr // 20:
        return x
    rms = float(np.sqrt(np.mean(x**2)))
    if rms > 1e-5:
        x = x * (target_rms / rms)
    peak = float(np.max(np.abs(x)))
    if peak > 0.92:
        x = x * (0.92 / peak)
    fade = min(len(x) // 4, int(0.012 * sr))
    if fade > 0:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    return x


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


# ---------------------------------------------------------------------- eSpeak NG ----
class EspeakProvider:
    name = "espeak"
    quality = "formant synthesis: clear but robotic; fallback voice"
    license = "eSpeak NG (GPL-3.0 engine; generated speech is unrestricted output)"
    cost_per_char = 0.0
    _lock = threading.Lock()
    _lib = None
    _rate = 22050

    def __init__(self) -> None:
        self.binary = shutil.which("espeak-ng") or shutil.which("espeak")

    def _load(self):
        if EspeakProvider._lib is not None:
            return EspeakProvider._lib
        try:
            import espeakng_loader
        except ImportError as exc:
            raise TTSUnavailable("eSpeak NG not found: pip install espeakng-loader, or install the espeak-ng package") from exc
        lib = ctypes.CDLL(espeakng_loader.get_library_path())
        lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
                                     ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        data_parent = os.path.dirname(espeakng_loader.get_data_path())
        rate = lib.espeak_Initialize(2, 0, data_parent.encode(), 0)   # 2 = AUDIO_OUTPUT_SYNCHRONOUS
        if rate <= 0:
            raise TTSUnavailable("eSpeak NG failed to initialise")
        EspeakProvider._lib, EspeakProvider._rate = lib, rate
        return lib

    def available(self) -> tuple[bool, str]:
        if self.binary:
            return True, f"binary {self.binary}"
        try:
            self._load()
            return True, "library via espeakng-loader"
        except TTSUnavailable as exc:
            return False, str(exc)

    def synthesize(self, text: str, profile: dict) -> np.ndarray:
        voice = profile.get("voice", "en-us")
        rate, pitch = int(profile.get("rate", 140)), int(profile.get("pitch", 50))
        if self.binary:
            proc = subprocess.run([self.binary, "-v", voice, "-s", str(rate), "-p", str(pitch), "--stdout", text],
                                  capture_output=True, timeout=60)
            if proc.returncode != 0 or len(proc.stdout) < 100:
                raise TTSError(f"espeak failed: {proc.stderr.decode(errors='replace')[:200]}")
            import io

            with wave.open(io.BytesIO(proc.stdout), "rb") as w:
                sr = w.getframerate()
                pcm = np.frombuffer(w.readframes(10**9), dtype="<i2").astype(np.float32) / 32768.0
            return resample(pcm, sr, SR)
        lib = self._load()
        chunks: list[np.ndarray] = []
        CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)

        def cb(wav, n, events):
            if wav and n > 0:
                chunks.append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
            return 0

        ref = CB(cb)
        with EspeakProvider._lock:
            lib.espeak_SetSynthCallback(ref)
            if lib.espeak_SetVoiceByName(voice.encode()) != 0:
                lib.espeak_SetVoiceByName(b"en-us")
            lib.espeak_SetParameter(1, rate, 0)
            lib.espeak_SetParameter(3, pitch, 0)
            data = text.encode("utf-8")
            err = lib.espeak_Synth(data, len(data) + 1, 0, 1, 0, 1, None, None)
            lib.espeak_Synchronize()
        if err != 0 or not chunks:
            raise TTSError(f"espeak synthesis error {err}")
        pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
        return resample(pcm, EspeakProvider._rate, SR)


# ------------------------------------------------------------------------- Kokoro ----
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


class KokoroProvider:
    name = "kokoro"
    quality = "neural voice (Kokoro-82M): natural; production default"
    license = "Kokoro-82M model weights: Apache-2.0; kokoro-onnx runtime: MIT"
    cost_per_char = 0.0
    _engine = None

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = Path(model_dir)

    def available(self) -> tuple[bool, str]:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return False, "kokoro-onnx not installed (pip install -r requirements-voice.txt)"
        missing = [f for f in KOKORO_FILES if not (self.model_dir / f).is_file()]
        if missing:
            return False, f"model files missing in {self.model_dir}: {', '.join(missing)} (python -m wonderland voices install)"
        return True, str(self.model_dir)

    def _load(self):
        if KokoroProvider._engine is None:
            ok, why = self.available()
            if not ok:
                raise TTSUnavailable(why)
            from kokoro_onnx import Kokoro

            KokoroProvider._engine = Kokoro(str(self.model_dir / "kokoro-v1.0.onnx"), str(self.model_dir / "voices-v1.0.bin"))
        return KokoroProvider._engine

    def synthesize(self, text: str, profile: dict) -> np.ndarray:
        engine = self._load()
        pitch = float(profile.get("pitch", 1.0))
        speed = float(profile.get("speed", 1.0)) / pitch
        samples, sr = engine.create(text, voice=profile.get("voice", "af_heart"), speed=max(0.5, min(2.0, speed)), lang="en-us")
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        if len(x) == 0:
            raise TTSError("kokoro returned no audio")
        return resample(x, int(sr * pitch), SR)     # play faster = higher pitch; tempo already compensated


def install_kokoro(model_dir: Path, log=print) -> list[dict]:
    """Download the Kokoro model files. Returns [{file, bytes, sha256, url}] for the licence ledger."""
    model_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for name, url in KOKORO_FILES.items():
        dest = model_dir / name
        if not dest.is_file():
            log(f"downloading {name} …")
            tmp = dest.with_suffix(dest.suffix + ".part")
            req = urllib.request.Request(url, headers={"User-Agent": "wonderland-studio"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
                shutil.copyfileobj(r, fh, 1024 * 1024)
            os.replace(tmp, dest)
        h = hashlib.sha256()
        with open(dest, "rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(block)
        out.append({"file": name, "bytes": dest.stat().st_size, "sha256": h.hexdigest(), "url": url})
    return out


# --------------------------------------------------------------------- ElevenLabs ----
class ElevenLabsProvider:
    name = "elevenlabs"
    quality = "premium neural voices (paid)"
    license = "ElevenLabs terms: commercial use on paid plans"
    cost_per_char = 0.00018     # USD, estimate for budgeting; override in studio.yaml → budget.rates

    def __init__(self, authorized: bool, base_url: str | None = None) -> None:
        self.authorized = authorized
        self.base_url = (base_url or os.getenv("ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io").rstrip("/")
        self.key = os.getenv("ELEVENLABS_API_KEY", "")

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, "ELEVENLABS_API_KEY not set"
        if not self.authorized:
            return False, "paid provider not authorized (budget.paid_providers_authorized is false)"
        return True, "key present and spending authorized"

    def synthesize(self, text: str, profile: dict) -> np.ndarray:
        ok, why = self.available()
        if not ok:
            raise TTSUnavailable(why)
        voice_id = profile.get("voice_id")
        if not voice_id:
            raise TTSUnavailable("no ElevenLabs voice_id in this character's voice profile (config/universe.yaml)")
        body = json.dumps({"text": text, "model_id": profile.get("model_id", "eleven_multilingual_v2"),
                           "voice_settings": {"stability": profile.get("stability", 0.5), "similarity_boost": 0.8}}).encode()
        req = urllib.request.Request(f"{self.base_url}/v1/text-to-speech/{voice_id}?output_format=pcm_44100", data=body,
                                     headers={"xi-api-key": self.key, "Content-Type": "application/json", "Accept": "audio/pcm"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            raise TTSError(f"ElevenLabs HTTP {exc.code}", transient=exc.code in (429, 500, 502, 503, 504)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TTSError(f"ElevenLabs unreachable: {type(exc).__name__}", transient=True) from exc
        if len(raw) < 2000:
            raise TTSError("ElevenLabs returned too little audio")
        return np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


# ---------------------------------------------------------------------- the desk ----
class VoiceDesk:
    """Picks the first available provider and synthesizes cached, polished clips."""

    def __init__(self, order: list[str], cache_dir: Path, model_dir: Path, paid_authorized: bool = False):
        self.cache_dir = Path(cache_dir)
        self.providers = {"espeak": EspeakProvider(), "kokoro": KokoroProvider(model_dir),
                          "elevenlabs": ElevenLabsProvider(paid_authorized)}
        self.order = [p for p in order if p in self.providers]
        self._active = None

    def doctor(self) -> list[dict]:
        rows = []
        for name in self.order:
            p = self.providers[name]
            ok, detail = p.available()
            rows.append({"provider": name, "available": ok, "detail": detail, "quality": p.quality, "license": p.license,
                         "cost_per_char_usd": p.cost_per_char})
        return rows

    def active(self):
        if self._active is None:
            for name in self.order:
                if self.providers[name].available()[0]:
                    self._active = self.providers[name]
                    break
            else:
                raise TTSUnavailable("no voice provider available: " + "; ".join(f"{r['provider']}: {r['detail']}" for r in self.doctor()))
        return self._active

    def speak(self, text: str, voice_profiles: dict) -> dict:
        """Return {"path", "duration", "provider", "chars", "cost_usd", "cached"} for one line."""
        provider = self.active()
        profile = voice_profiles.get(provider.name) or {}
        text = clean_text(text)
        key = hashlib.sha1(json.dumps([provider.name, profile, text], sort_keys=True).encode()).hexdigest()[:20]
        path = self.cache_dir / provider.name / f"{key}.wav"
        cached = path.is_file()
        if not cached:
            x = polish(provider.synthesize(text, profile))
            if len(x) < SR * 0.15:
                raise TTSError(f"voice clip too short for: {text!r}")
            write_wav(path, x)
        x, _ = read_wav(path)
        return {"path": str(path), "duration": len(x) / SR, "provider": provider.name, "chars": len(text),
                "cost_usd": 0.0 if cached else round(len(text) * provider.cost_per_char, 6), "cached": cached,
                "license": provider.license}


def loudness_envelope(x: np.ndarray, fps: int, sr: int = SR) -> list[float]:
    """Per-video-frame mouth openness 0..1 from a voice clip (for lip-sync)."""
    hop = sr // fps
    n = max(1, len(x) // hop)
    env = np.array([float(np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2))) if len(x[i * hop:(i + 1) * hop]) else 0.0 for i in range(n)])
    if env.max() <= 1e-6:
        return [0.0] * n
    env = np.clip(env / (np.percentile(env, 92) + 1e-6), 0, 1) ** 0.75
    env[env < 0.24] = 0.0          # mouths close between syllables and words
    smooth = np.copy(env)
    for i in range(1, n):
        smooth[i] = 0.7 * env[i] + 0.3 * smooth[i - 1]
    return [round(float(v), 3) for v in smooth]
