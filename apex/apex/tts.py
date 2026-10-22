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

    def rupiah(m: re.Match) -> str:
        return f"{id_number_words(int(m.group(1).replace('.', '')))} rupiah"

    text = re.sub(r"Rp\.?\s?(\d{1,3}(?:\.\d{3})+|\d+)", rupiah, text)
    text = re.sub(r"\b(\d{1,3}(?:\.\d{3})+)\b", lambda m: id_number_words(int(m.group(1).replace(".", ""))), text)
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
        subprocess.run(["espeak-ng", "-v", language, "-s", str(self.speed), "-w", str(out_wav), spoken],
                       check=True, capture_output=True)
        if not out_wav.exists() or out_wav.stat().st_size < 1000 or probe_duration(out_wav) <= 0:
            raise RuntimeError(f"espeak-ng produced no usable audio for: {text[:40]!r}")
        return out_wav
