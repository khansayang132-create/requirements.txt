"""eSpeak NG adapter: local formant synthesis in 100+ languages, SSML prosody, phoneme events with timestamps.

Honest quality note: intelligible but robotic. Emotion is approximated with prosody (rate, pitch, range, volume,
pauses, emphasis); there is no emotional voice model behind it.
"""

from __future__ import annotations

import ctypes
import os
import threading
from xml.sax.saxutils import escape

import numpy as np

from .base import SR, Engine, EngineError, Synth, Unsupported, resample


class _EVENT(ctypes.Structure):
    class _ID(ctypes.Union):
        _fields_ = [("number", ctypes.c_int), ("name", ctypes.c_char_p), ("string", ctypes.c_char * 8)]

    _fields_ = [("type", ctypes.c_int), ("unique_identifier", ctypes.c_uint), ("text_position", ctypes.c_int), ("length", ctypes.c_int),
                ("audio_position", ctypes.c_int), ("sample", ctypes.c_int), ("user_data", ctypes.c_void_p), ("id", _ID)]


_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.POINTER(_EVENT))
_LOCK = threading.Lock()
_LIB = None
_RATE = 22050
_DATA = None
EV_PHONEME = 7
SSML = 0x10
CHARS_UTF8 = 1


def _load():
    global _LIB, _RATE, _DATA
    if _LIB is not None:
        return _LIB
    try:
        import espeakng_loader
    except ImportError as e:
        raise EngineError("eSpeak NG not installed (pip install espeakng-loader)") from e
    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                 ctypes.c_void_p, ctypes.c_void_p]
    lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    _DATA = espeakng_loader.get_data_path()
    rate = lib.espeak_Initialize(2, 0, os.path.dirname(_DATA).encode(), 0x0001)
    if rate <= 0:
        raise EngineError("eSpeak NG failed to initialise")
    _LIB, _RATE = lib, rate
    return lib


VARIANTS = {"female": ["f1", "f2", "f3", "f4", "f5"], "male": ["m1", "m2", "m3", "m4", "m5", "m6", "m7"], "neutral": ["klatt", "klatt2"]}


class EspeakEngine(Engine):
    name = "espeak-ng"
    license = "GPL-3.0-or-later (engine); generated audio is not restricted"
    quality_rank = 10
    offline = True

    def languages(self) -> list[str]:
        _load()
        return sorted(f[:-5] for f in os.listdir(_DATA) if f.endswith("_dict"))

    def capabilities(self) -> dict:
        return {"languages": self.languages(), "voices": [f"{g}:{v}" for g, vs in VARIANTS.items() for v in vs],
                "emotion": "prosody", "ssml": True, "phoneme_timing": True, "speakers": len(sum(VARIANTS.values(), [])),
                "commercial_use": "yes", "voice_cloning": False, "speech_to_speech": False}

    def health(self) -> tuple[str, str]:
        try:
            _load()
            s = self.synthesize("test", {"language": "en-us", "variant": "m1"}, {})
            ok = len(s.audio) > SR * 0.1 and float(np.abs(s.audio).max()) > 0.05
            return ("PASS", f"spoke a test word ({len(s.audio) / SR:.2f}s, {len(s.phonemes or [])} phonemes); "
                            f"{len(self.languages())} languages") if ok else ("FAIL", "silent test output")
        except Exception as e:  # noqa: BLE001
            return "BLOCKED", str(e)

    def _ssml(self, text: str, c: dict) -> str:
        body = escape(text)
        for w in c.get("emphasis", []):
            body = body.replace(escape(w), f'<emphasis level="strong">{escape(w)}</emphasis>', 1)
        pre = f'<break time="{int(c.get("pause_before", 0) * 1000)}ms"/>' if c.get("pause_before") else ""
        post = f'<break time="{int(c.get("pause_after", 0) * 1000)}ms"/>' if c.get("pause_after") else ""
        return (f'<speak>{pre}<prosody rate="{int(c.get("rate_pct", 100))}%" pitch="{c.get("pitch_shift_pct", 0):+d}%" '
                f'volume="{int(c.get("volume_pct", 100))}%">{body}</prosody>{post}</speak>')

    def synthesize(self, text: str, voice: dict, controls: dict) -> Synth:
        lib = _load()
        lang = voice.get("language", "en-us")
        if lang.split("-")[0].split("_")[0] not in self.languages():
            raise Unsupported(f"eSpeak NG has no '{lang}' language")
        name = lang + (f"+{voice['variant']}" if voice.get("variant") else "")
        chunks, events = [], []

        def cb(wav, n, ev):
            if wav and n > 0:
                chunks.append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
            i = 0
            while ev and ev[i].type != 0:
                if ev[i].type == EV_PHONEME:
                    events.append((ev[i].audio_position, bytes(ev[i].id.string).split(b"\0")[0].decode("ascii", "replace")))
                i += 1
            return 0

        ref = _CB(cb)
        data = self._ssml(text, controls).encode("utf-8")
        with _LOCK:
            lib.espeak_SetSynthCallback(ref)
            if lib.espeak_SetVoiceByName(name.encode()) != 0:
                raise Unsupported(f"eSpeak NG voice '{name}' not found")
            lib.espeak_SetParameter(1, int(voice.get("rate_wpm", 150)), 0)
            lib.espeak_SetParameter(3, int(voice.get("pitch", 50)), 0)
            lib.espeak_SetParameter(4, int(voice.get("range", 60) * controls.get("range_mul", 1.0)), 0)
            err = lib.espeak_Synth(data, len(data) + 1, 0, 1, 0, CHARS_UTF8 | SSML, None, None)
            lib.espeak_Synchronize()
        if err != 0 or not chunks:
            raise EngineError(f"eSpeak synthesis error {err}")
        pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
        dur = len(pcm) / _RATE
        ph = []
        for k, (ms, sym) in enumerate(events):
            t1 = events[k + 1][0] / 1000 if k + 1 < len(events) else dur
            if sym and t1 > ms / 1000:
                ph.append((round(ms / 1000, 3), round(t1, 3), sym))
        x = resample(pcm, _RATE, SR)
        x -= float(x.mean())
        peak = float(np.abs(x).max()) or 1.0
        x = x / peak * 0.7 * min(1.0, controls.get("volume_pct", 100) / 100)
        return Synth(x, ph, "engine", {"voice_name": name, "native_rate": _RATE})
