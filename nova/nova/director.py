"""Intelligent voice director: decides how each sentence is spoken and turns that into the
selected engine's real controls (rate, pitch, intonation range, volume, emphasis) plus pauses
and breaths, which the pipeline inserts as measured silence — not as tags in the text."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .script_judge import EMOTIONS, emphasis_candidates
from .textutil import sentence_language, split_sentences, words
from .tts.base import Capabilities, Prosody

# tone label, rate, pitch (semitones), intonation range, volume (dB)
TONES = {
    "neutral": ("Natural tone", 1.00, 0.0, 1.0, 0.0),
    "happiness": ("Warm tone", 1.02, 1.5, 1.25, 0.5),
    "sadness": ("Gentle, sad tone", 0.86, -1.5, 0.8, -2.0),
    "excitement": ("Excited tone", 1.10, 3.0, 1.45, 1.5),
    "confidence": ("Confident tone", 0.98, 0.0, 1.1, 1.0),
    "authority": ("Authoritative tone", 0.93, -2.0, 0.9, 1.5),
    "romance": ("Soft, romantic tone", 0.88, -0.5, 1.1, -1.5),
    "professional": ("Professional narration", 0.97, 0.0, 1.0, 0.0),
    "documentary": ("Documentary narration", 0.92, -1.0, 0.95, 0.0),
    "commercial": ("Commercial, upbeat tone", 1.06, 2.0, 1.3, 1.0),
}
MODE_SCALE = {"natural": 0.8, "professional": 0.6, "expressive": 1.25}
PAUSE_BASE = {".": 450, "!": 500, "?": 550, "…": 800}
MODE_PAUSE = {"natural": 1.0, "professional": 1.1, "expressive": 1.3}


@dataclass
class Direction:
    index: int
    text: str
    language: str
    emotion: str
    tone: str
    prosody: Prosody
    pause_after_ms: int
    breath_after_word: int | None = None
    scene: int | None = None
    applied: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["prosody"] = asdict(self.prosody)
        return d


def _sentence_emotion(sentence: str, fallback: str) -> str:
    tokens = {w.lower() for w in words(sentence)}
    best, hits = fallback, 0
    for e, lex in EMOTIONS.items():
        n = len(tokens & (lex["en"] | lex["id"])) + (1.5 if e == "excitement" and sentence.endswith("!") else 0)
        if n > hits:
            best, hits = e, n
    return best


def direct(text: str, mode: str = "natural", emotion_override: str | None = None, scene: int | None = None,
           script_language: str = "en") -> list[Direction]:
    sentences = split_sentences(text)
    scale = MODE_SCALE.get(mode, 1.0)
    out = []
    for i, s in enumerate(sentences):
        # A sentence without its own emotion words stays neutral: inheriting the script's dominant
        # emotion let one keyword (e.g. "ternyata") make every line sound excited.
        emo = emotion_override or _sentence_emotion(s, "neutral")
        tone, rate, pitch, rng, vol = TONES.get(emo, TONES["neutral"])
        prosody = Prosody(
            rate=round(1 + (rate - 1) * scale, 3),
            pitch_semitones=round(pitch * scale, 2),
            pitch_range=round(1 + (rng - 1) * scale, 3),
            volume_db=round(vol * scale, 2),
            emphasis=emphasis_candidates(s, limit=1 if mode == "professional" else 2),
        )
        end = "…" if s.endswith(("...", "…")) else s.rstrip("\"'”)")[-1:]
        pause = PAUSE_BASE.get(end, 450) * MODE_PAUSE.get(mode, 1.0)
        if i == len(sentences) - 1:
            pause = 0
        n = len(words(s))
        breath = None
        if n > 14:
            commas = [len(words(s[:m.start()])) for m in re.finditer(r"[,;]", s)]
            breath = min(commas, key=lambda c: abs(c - n / 2)) if commas else n // 2
        lang = sentence_language(s)
        out.append(Direction(index=i, text=s, language=lang if lang in ("en", "id") else script_language,
                             emotion=emo, tone=tone, prosody=prosody, pause_after_ms=int(pause),
                             breath_after_word=breath, scene=scene))
    return out


def map_to_engine(d: Direction, caps: Capabilities, converting: bool) -> dict:
    """Which controls the engine applies itself and which the pipeline applies afterwards
    (pitch/range via WORLD conversion, volume via gain)."""
    return {
        "rate": "engine" if caps.rate else "not supported",
        "pitch": "voice conversion" if converting else "engine" if caps.pitch else "WORLD pitch shift",
        "pitch_range": "voice conversion" if converting else "engine" if caps.pitch_range else "WORLD pitch shift",
        "volume": "engine" if caps.volume else "gain",
        "emphasis": "engine (SSML)" if caps.emphasis else "not supported",
        "pauses": "inserted silence",
        "breathing": "inserted silence",
    }


def render_script(directions: list[Direction]) -> str:
    lines = []
    for d in directions:
        lines.append(f"[{d.tone}]")
        text = d.text
        if d.breath_after_word:
            ws = text.split()
            text = " ".join(ws[:d.breath_after_word]) + " [Breath] " + " ".join(ws[d.breath_after_word:])
        lines.append(text)
        if d.prosody.emphasis:
            lines.append(f"[Emphasis: {', '.join(d.prosody.emphasis)}]")
        if d.pause_after_ms:
            lines.append(f"[Pause: {d.pause_after_ms}ms]")
        lines.append("")
    return "\n".join(lines).strip()
