"""SRT / WebVTT parsing, validation, conversion, and the optional Whisper fallback.

Whisper is optional: the publishing system works without it. ``transcribe_with_whisper``
raises ``DependencyMissing`` (with install instructions) when ``openai-whisper`` or the
``ffmpeg`` binary is absent, instead of producing an empty or fake transcript.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .exceptions import DependencyMissing, ValidationError
from .validators import ValidationResult

_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[,.](\d{3})"
_TIMING = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _seconds(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _fmt(t: float, sep: str) -> str:
    total_ms = int(round(t * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _parse_blocks(text: str, *, vtt: bool) -> list[Cue]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: list[Cue] = []
    for i, block in enumerate(blocks):
        lines = [ln for ln in block.split("\n")]
        if vtt and i == 0 and lines[0].startswith("WEBVTT"):
            continue
        if vtt and lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_idx = next((j for j, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            raise ValidationError("Caption file has a block without a timing line", [block[:80]])
        m = _TIMING.match(lines[timing_idx])
        if not m:
            raise ValidationError("Caption file has an invalid timing line", [lines[timing_idx][:80]])
        g = m.groups()
        start, end = _seconds(*g[0:4]), _seconds(*g[4:8])
        body = "\n".join(lines[timing_idx + 1 :]).strip()
        cues.append(Cue(start, end, body))
    return cues


def parse_srt(text: str) -> list[Cue]:
    return _parse_blocks(text, vtt=False)


def parse_vtt(text: str) -> list[Cue]:
    if not text.lstrip("﻿").startswith("WEBVTT"):
        raise ValidationError("Not a WebVTT file: it must start with 'WEBVTT'")
    return _parse_blocks(text, vtt=True)


def detect_format(path: str | Path, text: str | None = None) -> str:
    p = Path(path)
    if p.suffix.lower() == ".vtt":
        return "vtt"
    if p.suffix.lower() == ".srt":
        return "srt"
    text = text if text is not None else p.read_text(encoding="utf-8", errors="replace")
    return "vtt" if text.lstrip("﻿").startswith("WEBVTT") else "srt"


def load_cues(path: str | Path) -> tuple[str, list[Cue]]:
    text = Path(path).read_text(encoding="utf-8")
    fmt = detect_format(path, text)
    return fmt, (parse_vtt(text) if fmt == "vtt" else parse_srt(text))


def format_srt(cues: list[Cue]) -> str:
    return "\n".join(f"{i}\n{_fmt(c.start, ',')} --> {_fmt(c.end, ',')}\n{c.text}\n" for i, c in enumerate(cues, 1))


def format_vtt(cues: list[Cue]) -> str:
    body = "\n".join(f"{_fmt(c.start, '.')} --> {_fmt(c.end, '.')}\n{c.text}\n" for c in cues)
    return "WEBVTT\n\n" + body


def validate_cues(cues: list[Cue]) -> ValidationResult:
    r = ValidationResult()
    if not cues:
        r.errors.append("captions: no cues")
        return r
    prev_end = -1.0
    for i, c in enumerate(cues, 1):
        if c.end <= c.start:
            r.errors.append(f"cue {i}: end ({c.end:.3f}s) is not after start ({c.start:.3f}s)")
        if not c.text.strip():
            r.warnings.append(f"cue {i}: empty text")
        if c.start < prev_end - 0.001:
            r.warnings.append(f"cue {i}: overlaps the previous cue")
        prev_end = max(prev_end, c.end)
    r.info.update({"cues": len(cues), "duration_s": round(prev_end, 3)})
    return r


def validate_caption_file(path: str | Path) -> ValidationResult:
    r = ValidationResult()
    p = Path(path)
    if not p.is_file():
        r.errors.append(f"captions: file not found: {p}")
        return r
    try:
        fmt, cues = load_cues(p)
    except (ValidationError, UnicodeDecodeError) as exc:
        r.errors.append(f"captions: {exc}")
        return r
    r.info["format"] = fmt
    return r.merge(validate_cues(cues))


def convert(path: str | Path, to: str) -> str:
    _, cues = load_cues(path)
    return format_vtt(cues) if to == "vtt" else format_srt(cues)


def whisper_available() -> tuple[bool, str]:
    try:
        import whisper  # noqa: F401
    except ImportError:
        return False, "openai-whisper is not installed: pip install -r requirements-whisper.txt"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg binary not found on PATH (Whisper needs it): apt install ffmpeg / pkg install ffmpeg"
    return True, "ok"


def transcribe_with_whisper(media: str | Path, *, model: str = "base", language: str | None = None) -> list[Cue]:
    ok, why = whisper_available()
    if not ok:
        raise DependencyMissing(f"Whisper fallback unavailable: {why}")
    if not Path(media).is_file():
        raise ValidationError(f"Media file not found: {media}")
    import whisper

    asr = whisper.load_model(model)
    result = asr.transcribe(str(media), language=language, verbose=False)
    cues = [Cue(float(s["start"]), float(s["end"]), str(s["text"]).strip()) for s in result.get("segments", [])]
    if not cues:
        raise ValidationError("Whisper produced no segments (silent or unreadable audio?)")
    return cues
