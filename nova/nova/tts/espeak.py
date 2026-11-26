"""espeak-ng: always-local formant synthesiser. Rate, pitch, intonation range, volume and word
emphasis are applied through espeak-ng's own command-line and SSML controls."""
from __future__ import annotations

import html
import io
import re
import shutil
import subprocess

import numpy as np
import soundfile as sf

from .base import Capabilities, Prosody, TTSEngine, TTSUnavailable

LANG_VOICES = {"en": "en-us", "id": "id", "ur": "ur", "hi": "hi", "ms": "ms"}
BASE_WPM = 165
BASE_PITCH = 50  # espeak -p scale 0-99


class EspeakEngine(TTSEngine):
    name = "espeak-ng"
    capabilities = Capabilities(rate=True, pitch=True, pitch_range=True, volume=True, emphasis=True,
                                languages=tuple(LANG_VOICES))

    def __init__(self) -> None:
        self.binary = shutil.which("espeak-ng") or shutil.which("espeak")

    def available(self) -> bool:
        return self.binary is not None

    def voices(self) -> list[dict]:
        return [{"id": f"{v}+{var}", "language": lang, "variant": var}
                for lang, v in LANG_VOICES.items() for var in ("m3", "f3")]

    @staticmethod
    def _ssml(text: str, emphasis: list[str], range_pct: int = 0) -> str:
        body = html.escape(text, quote=False)
        for word in sorted(set(emphasis), key=len, reverse=True):
            if not word.strip():
                continue
            pattern = re.compile(rf"(?<![\w>])({re.escape(html.escape(word, quote=False))})(?![\w<])", re.I)
            body = pattern.sub(r'<emphasis level="strong">\1</emphasis>', body, count=1)
        if range_pct:
            body = f'<prosody range="{range_pct:+d}%">{body}</prosody>'
        return f"<speak>{body}</speak>"

    def synthesize(self, text: str, language: str, prosody: Prosody, voice: str | None = None) -> tuple[np.ndarray, int]:
        if not self.available():
            raise TTSUnavailable("espeak-ng is not installed (apt install espeak-ng / pkg install espeak)")
        voice = voice or f"{LANG_VOICES.get(language, 'en-us')}+m3"
        wpm = int(np.clip(BASE_WPM * prosody.rate, 80, 400))
        pitch = int(np.clip(BASE_PITCH + prosody.pitch_semitones * 4, 0, 99))
        rng = int(np.clip((prosody.pitch_range - 1.0) * 100, -90, 200))
        amp = int(np.clip(100 * 10 ** (prosody.volume_db / 20), 10, 200))
        cmd = [self.binary, "-m", "--stdout", "-v", voice, "-s", str(wpm), "-p", str(pitch),
               "-a", str(amp), self._ssml(text, prosody.emphasis, rng)]
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
        if proc.returncode != 0 or not proc.stdout:
            raise TTSUnavailable(f"espeak-ng failed: {proc.stderr.decode(errors='ignore')[:200]}")
        x, sr = sf.read(io.BytesIO(proc.stdout), dtype="float64")
        return x, int(sr)
