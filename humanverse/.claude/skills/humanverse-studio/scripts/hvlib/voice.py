"""Local speech with phoneme timing: eSpeak NG through its C API (no network, no account, no cost).

Each line is synthesised with phoneme events turned on, so we get the WAV *and* the exact start time of every
phoneme in milliseconds from the engine itself. Lip sync uses those times, not a guess.

Piper (neural, better sounding) is supported when `piper` and a voice model are installed locally; it is reported
BLOCKED otherwise. Never use a voice cloned from a real person without their written consent.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import threading
import wave
from pathlib import Path

import numpy as np

SR = 48000
_LOCK = threading.Lock()
_LIB = None
_RATE = 22050


class VoiceUnavailable(RuntimeError):
    pass


class EVENT(ctypes.Structure):
    class _ID(ctypes.Union):
        _fields_ = [("number", ctypes.c_int), ("name", ctypes.c_char_p), ("string", ctypes.c_char * 8)]

    _fields_ = [("type", ctypes.c_int), ("unique_identifier", ctypes.c_uint), ("text_position", ctypes.c_int),
                ("length", ctypes.c_int), ("audio_position", ctypes.c_int), ("sample", ctypes.c_int),
                ("user_data", ctypes.c_void_p), ("id", _ID)]


EV_PHONEME, EV_WORD, EV_END = 7, 1, 5
CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.POINTER(EVENT))


def _load():
    global _LIB, _RATE
    if _LIB is not None:
        return _LIB
    try:
        import espeakng_loader
    except ImportError as e:
        raise VoiceUnavailable("eSpeak NG missing: pip install espeakng-loader") from e
    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                 ctypes.c_void_p, ctypes.c_void_p]
    lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    data = os.path.dirname(espeakng_loader.get_data_path())
    rate = lib.espeak_Initialize(2, 0, data.encode(), 0x0001)        # synchronous, phoneme events on
    if rate <= 0:
        raise VoiceUnavailable("eSpeak NG failed to initialise")
    _LIB, _RATE = lib, rate
    return lib


def available() -> dict:
    out = {"espeak-ng": None, "piper": None}
    try:
        _load()
        out["espeak-ng"] = "PASS: libespeak-ng via espeakng-loader (GPL-3.0 engine; output unrestricted)"
    except VoiceUnavailable as e:
        out["espeak-ng"] = "BLOCKED: " + str(e)
    piper = shutil.which("piper")
    model = os.environ.get("HV_PIPER_VOICE")
    if piper and model and Path(model).is_file():
        out["piper"] = f"PASS: {piper} with {model}"
    else:
        out["piper"] = ("BLOCKED: " + ("piper not on PATH" if not piper else "no voice model (set HV_PIPER_VOICE to a local .onnx)")
                        + "; voice models download from huggingface.co")
    return out


def synthesize(text: str, profile: dict) -> tuple[np.ndarray, list[tuple[float, float, str]]]:
    """Returns (mono float32 at SR, [(t0, t1, phoneme)]) for one line."""
    lib = _load()
    chunks: list[np.ndarray] = []
    events: list[tuple[int, str]] = []
    total = [0]

    def cb(wav, n, ev):
        if wav and n > 0:
            chunks.append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
            total[0] += n
        i = 0
        while ev and ev[i].type != 0:
            e = ev[i]
            if e.type == EV_PHONEME:
                events.append((e.audio_position, bytes(e.id.string).split(b"\0")[0].decode("ascii", "replace")))
            i += 1
        return 0

    ref = CALLBACK(cb)
    with _LOCK:
        lib.espeak_SetSynthCallback(ref)
        if lib.espeak_SetVoiceByName(profile.get("espeak_voice", "en-us").encode()) != 0:
            lib.espeak_SetVoiceByName(b"en-us")
        lib.espeak_SetParameter(1, int(profile.get("rate", 150)), 0)      # words per minute
        lib.espeak_SetParameter(3, int(profile.get("pitch", 50)), 0)      # base pitch 0-100
        lib.espeak_SetParameter(4, int(profile.get("range", 60)), 0)      # pitch range (expressiveness)
        data = text.encode("utf-8")
        err = lib.espeak_Synth(data, len(data) + 1, 0, 1, 0, 1, None, None)
        lib.espeak_Synchronize()
    if err != 0 or not chunks:
        raise VoiceUnavailable(f"eSpeak synthesis error {err}")
    pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
    dur = len(pcm) / _RATE
    ph = []
    for k, (ms, name) in enumerate(events):
        t0 = ms / 1000.0
        t1 = events[k + 1][0] / 1000.0 if k + 1 < len(events) else dur
        if name and t1 > t0:
            ph.append((t0, t1, name))
    x = np.interp(np.arange(int(dur * SR)) / SR, np.arange(len(pcm)) / _RATE, pcm).astype(np.float32)
    # gentle polish: remove DC, soft high-shelf cut of eSpeak buzz, normalise to a speech level
    x -= x.mean()
    k = np.exp(-2 * np.pi * 6500 / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):          # one-pole low-pass, blended with the dry signal
        acc = (1 - k) * x[i] + k * acc
        y[i] = acc
    x = 0.55 * x + 0.45 * y
    peak = float(np.max(np.abs(x))) or 1.0
    x = x / peak * 0.7
    return x, ph


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def render_lines(lines: list[dict], voices: dict, out_dir: Path) -> list[dict]:
    """lines: [{line_id, character_id, text}] -> writes <line_id>.wav and returns manifest rows with timing."""
    rows = []
    for ln in lines:
        prof = voices[ln["character_id"]]
        x, ph = synthesize(ln["text"], prof)
        wav = out_dir / f"{ln['line_id']}.wav"
        write_wav(wav, x)
        rms = float(np.sqrt(np.mean(x ** 2)))
        rows.append({**ln, "wav": str(wav), "duration": round(len(x) / SR, 3), "rms": round(rms, 4), "engine": "espeak-ng",
                     "phonemes": [[round(a, 3), round(b, 3), p] for a, b, p in ph]})
    (out_dir / "lines.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows
