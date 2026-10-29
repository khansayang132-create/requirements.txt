"""Text-to-speech: replaceable providers plus Indonesian pronunciation normalization."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Protocol

from .media import probe_duration


class TTSUnavailable(RuntimeError):
    pass


class TTSProvider(Protocol):
    name: str
    quality_note: str

    def synthesize(self, text: str, language: str, out_wav: Path) -> Path: ...


_ONES = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan",
         "sepuluh", "sebelas"]


def _id_below_1000(n: int) -> str:
    if n < 12:
        return _ONES[n]
    if n < 20:
        return f"{_ONES[n - 10]} belas"
    if n < 100:
        tens, rest = divmod(n, 10)
        return f"{_ONES[tens]} puluh" + (f" {_ONES[rest]}" if rest else "")
    hundreds, rest = divmod(n, 100)
    head = "seratus" if hundreds == 1 else f"{_ONES[hundreds]} ratus"
    return head + (f" {_id_below_1000(rest)}" if rest else "")


def id_number_words(n: int) -> str:
    """Indonesian words for 0 <= n < 10^12, e.g. 25000 -> 'dua puluh lima ribu'."""
    if n == 0:
        return "nol"
    parts = []
    for value, word in ((10**9, "miliar"), (10**6, "juta"), (1000, "ribu")):
        q, n = divmod(n, value)
        if q:
            parts.append("seribu" if (value == 1000 and q == 1) else f"{id_number_words(q)} {word}")
    if n:
        parts.append(_id_below_1000(n))
    return " ".join(parts)


def normalize_for_speech(text: str, language: str) -> str:
    """Make prices and numbers speakable. Indonesian uses '.' as the thousands separator."""
    if language != "id":
        return text

    number = r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?"  # 1.250.000 or 1,5 (decimal comma)

    def spoken_number(m: re.Match) -> str:
        words = id_number_words(int(m.group(1).replace(".", "")))
        if m.group(2):  # decimals are read digit by digit: 2,25 -> dua koma dua lima
            words += " koma " + " ".join(id_number_words(int(d)) for d in m.group(2))
        return words

    shorthand = {"rb": "ribu", "k": "ribu", "jt": "juta"}  # social-media forms: Rp10rb, Rp50k, Rp1,5jt

    def rupiah(m: re.Match) -> str:  # "Rp1,5 juta" -> "satu koma lima juta rupiah"
        scale = (m.group(3) or "").lower()
        return f"{spoken_number(m)}{' ' + shorthand.get(scale, scale) if scale else ''} rupiah"

    text = re.sub(rf"Rp\.?\s?{number}(?:\s*((?i:ribu|juta|miliar|triliun|rb|jt|k))\b)?", rupiah, text)
    text = re.sub(rf"\b{number}\b", lambda m: spoken_number(m) if (m.group(2) or "." in m.group(1)) else m.group(0), text)
    text = re.sub(r"\b(\d+)\s?[xX](?![A-Za-z])", r"\1 × ", text)  # "3x sehari" -> "tiga kali sehari"
    text = re.sub(r"\b(\d+)\b", lambda m: id_number_words(int(m.group(1))), text)
    text = re.sub(r"\s*×\s*", " kali ", text)
    return re.sub(r"\s+", " ", text).strip()


class EspeakProvider:
    """Offline espeak-ng. Real synthesized speech, but robotic; fine for drafts and pipeline tests."""

    name = "espeak-ng"
    quality_note = "offline formant synthesis (robotic); replace with a neural TTS provider for publishing"

    def __init__(self, speed_wpm: int = 175):
        if not shutil.which("espeak-ng"):
            raise TTSUnavailable("espeak-ng is not installed (apt-get install espeak-ng)")
        self.speed = speed_wpm

    def synthesize(self, text: str, language: str, out_wav: Path) -> Path:
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        spoken = normalize_for_speech(text, language)
        # "--" ends the options: narration starting with "-" was read as a flag and produced no audio.
        subprocess.run(["espeak-ng", "-v", language, "-s", str(self.speed), "-w", str(out_wav), "--", spoken],
                       check=True, capture_output=True)
        if not out_wav.exists() or out_wav.stat().st_size < 1000 or probe_duration(out_wav) <= 0:
            raise RuntimeError(f"espeak-ng produced no usable audio for: {text[:40]!r}")
        return out_wav


class ElevenLabsProvider:
    """Natural neural voices through the ElevenLabs text-to-speech API."""

    quality_note = "neural TTS (natural); suitable for publishing"

    def __init__(self, api_key: str, voice_id: str, model_id: str = "eleven_multilingual_v2",
                 base_url: str = "https://api.elevenlabs.io"):
        if not api_key:
            raise TTSUnavailable("ELEVENLABS_API_KEY is not set")
        self.api_key, self.voice_id, self.model_id = api_key, voice_id, model_id
        self.base_url = base_url.rstrip("/")
        self.name = f"elevenlabs:{voice_id}:{model_id}"

    def synthesize(self, text: str, language: str, out_wav: Path) -> Path:
        import json
        import urllib.error
        import urllib.request

        out_wav.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            f"{self.base_url}/v1/text-to-speech/{self.voice_id}?output_format=mp3_44100_128",
            data=json.dumps({"text": normalize_for_speech(text, language), "model_id": self.model_id,
                             "language_code": language}).encode(),
            method="POST", headers={"xi-api-key": self.api_key, "content-type": "application/json",
                                    "accept": "audio/mpeg"})
        try:
            # The ElevenLabs base URL comes from configuration.
            with urllib.request.urlopen(req, timeout=120) as r:  # nosec B310
                audio = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (401, 402, 403):
                # Bad key, unpaid invoice or quota: setup problems, not worth retrying.
                raise TTSUnavailable(f"ElevenLabs refused the request ({e.code}): {detail}") from e
            raise RuntimeError(f"ElevenLabs error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"ElevenLabs unreachable: {e.reason}") from e
        mp3 = out_wav.with_suffix(".mp3")
        mp3.write_bytes(audio)
        subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(mp3), "-ar", "44100", "-ac", "1",
                        str(out_wav)], check=True, capture_output=True)
        mp3.unlink()
        if probe_duration(out_wav) <= 0:
            raise RuntimeError(f"ElevenLabs returned no usable audio for: {text[:40]!r}")
        return out_wav


# Nilasari: clear, natural Indonesian voice made for education and TikTok narration.
DEFAULT_ELEVENLABS_VOICE = "NPDHDOOQCSyifTJZOe6J"


def tts_from_env() -> TTSProvider:
    """ElevenLabs when ELEVENLABS_API_KEY is set, otherwise offline espeak-ng."""
    import os

    if os.getenv("ELEVENLABS_API_KEY"):
        return ElevenLabsProvider(os.environ["ELEVENLABS_API_KEY"],
                                  os.getenv("APEX_VOICE_ID", DEFAULT_ELEVENLABS_VOICE),
                                  os.getenv("APEX_TTS_MODEL", "eleven_multilingual_v2"))
    return EspeakProvider()
