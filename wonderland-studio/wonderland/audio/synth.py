"""Original music and sound effects, synthesized from code.

Nothing here is sampled or downloaded: every note is a sum of sine/triangle partials
with an envelope, every tune is composed by ``compose`` from a seed. That makes each
episode's music original, reproducible (same seed → same tune) and free of any
licence question. The licence ledger records "composed in-house" with the seed.

Moods:
  bright / adventure / warm : mallet melody, plucked broken chords, soft bass, shaker
  song                      : the same band with a light kick so rhymes can sit on the beat
  calm                      : music-box melody over slow pads, no percussion (bedtime)
"""

from __future__ import annotations

import math
import random

import numpy as np

SR = 44100
PENTA = [0, 2, 4, 7, 9]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
PROGRESSIONS = [[0, 4, 5, 3], [0, 3, 4, 0], [0, 5, 3, 4], [0, 3, 0, 4], [0, 5, 1, 4]]
RHYTHMS = [[1, 1, 1, 1], [1, 1, 2], [2, 1, 1], [1.5, 0.5, 1, 1], [2, 2], [1, 1, 1, 0.5, 0.5], [0.5, 0.5, 1, 2], [1, 0.5, 0.5, 2]]
MOODS = {
    "bright":    {"tempo": (102, 114), "perc": True, "kick": False, "lead": "mallet", "level": 1.0},
    "adventure": {"tempo": (108, 120), "perc": True, "kick": False, "lead": "mallet", "level": 1.0},
    "warm":      {"tempo": (92, 104), "perc": True, "kick": False, "lead": "pluck", "level": 0.95},
    "song":      {"tempo": (106, 116), "perc": True, "kick": True, "lead": "mallet", "level": 1.05},
    "calm":      {"tempo": (64, 74), "perc": False, "kick": False, "lead": "box", "level": 0.85},
}


def freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _t(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR), dtype=np.float32) / SR


def mallet(f: float, dur: float = 0.9) -> np.ndarray:
    t = _t(dur)
    x = np.sin(2 * math.pi * f * t) * np.exp(-t * 5.5)
    x += 0.32 * np.sin(2 * math.pi * 4 * f * t) * np.exp(-t * 16)
    x += 0.12 * np.sin(2 * math.pi * 9.2 * f * t) * np.exp(-t * 34)
    return (x * np.minimum(1, t * 400)).astype(np.float32)


def music_box(f: float, dur: float = 1.6) -> np.ndarray:
    t = _t(dur)
    x = np.sin(2 * math.pi * f * t) * np.exp(-t * 2.6)
    x += 0.4 * np.sin(2 * math.pi * 3.01 * f * t) * np.exp(-t * 6)
    x += 0.15 * np.sin(2 * math.pi * 6.3 * f * t) * np.exp(-t * 12)
    return (x * np.minimum(1, t * 300)).astype(np.float32)


def pluck(f: float, dur: float = 0.7) -> np.ndarray:
    t = _t(dur)
    x = sum(np.sin(2 * math.pi * f * k * t) / (k * k) for k in (1, 3, 5))
    return (x * np.exp(-t * 6.5) * np.minimum(1, t * 300)).astype(np.float32)


def pad(freqs: list[float], dur: float) -> np.ndarray:
    t = _t(dur)
    x = np.zeros_like(t)
    for f in freqs:
        x += np.sin(2 * math.pi * f * t) + 0.5 * np.sin(2 * math.pi * f * 1.004 * t) + 0.25 * np.sin(2 * math.pi * 2 * f * t)
    env = np.minimum(1, t / 0.35) * np.minimum(1, (dur - t) / 0.45).clip(0, 1)
    return (x / max(1, len(freqs)) * env).astype(np.float32)


def bass(f: float, dur: float = 0.8) -> np.ndarray:
    t = _t(dur)
    x = np.sin(2 * math.pi * f * t) + 0.3 * np.sin(2 * math.pi * 2 * f * t)
    return (x * np.exp(-t * 3.2) * np.minimum(1, t * 120)).astype(np.float32)


def shaker(dur: float = 0.07, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = rng.standard_normal(n).astype(np.float32)
    x = np.diff(x, prepend=0)          # crude high-pass
    return x * np.exp(-np.arange(n) / SR * 70).astype(np.float32)


def kick(dur: float = 0.22) -> np.ndarray:
    t = _t(dur)
    ph = 2 * math.pi * (55 * t + (120 - 55) / 28 * (1 - np.exp(-t * 28)))
    return (np.sin(ph) * np.exp(-t * 16)).astype(np.float32)


def _add(buf: np.ndarray, x: np.ndarray, at: float, gain: float = 1.0) -> None:
    i = int(at * SR)
    if i >= len(buf) or i < 0:
        return
    n = min(len(x), len(buf) - i)
    buf[i:i + n] += x[:n] * gain


def compose(seed: int, duration: float, mood: str = "bright", bars_hint: int | None = None) -> tuple[np.ndarray, dict]:
    """Compose and render ``duration`` seconds of background music. Returns (mono float32, info)."""
    cfg = MOODS.get(mood, MOODS["bright"])
    rng = random.Random(seed)
    tempo = rng.randint(*cfg["tempo"])
    beat = 60.0 / tempo
    bar = 4 * beat
    root = rng.choice([60, 62, 65, 67, 58])
    prog = rng.choice(PROGRESSIONS)
    n_bars = max(4, math.ceil(duration / bar) + 1)

    def chord(deg: int) -> list[int]:
        return [root + MAJOR[(deg + k) % 7] + 12 * ((deg + k) // 7) for k in (0, 2, 4)]

    # melody: an 8-bar tune in A A' B A form made from two rhythm cells and pentatonic steps
    def phrase(seed_idx: int, end_on: int) -> list[tuple[float, int]]:
        r = random.Random(seed * 31 + seed_idx)
        notes, idx = [], r.choice([0, 1, 2])
        for b in range(2):
            pattern = r.choice(RHYTHMS)
            pos = 0.0
            for length in pattern:
                idx = max(0, min(len(PENTA) + 2, idx + r.choice([-1, -1, 0, 1, 1, 2, -2])))
                octave, step = divmod(idx, len(PENTA))
                notes.append((b * 4 + pos, length, root + 12 + PENTA[step] + 12 * octave))
                pos += length
        last = notes[-1]
        notes[-1] = (last[0], last[1], root + 12 + end_on)
        return notes

    A, A2, B = phrase(1, 4), phrase(1, 0), phrase(2, 7)
    A2 = A[:-2] + A2[-2:]
    tune = [A, A2, B, A2]          # each phrase = 2 bars → 8 bars

    buf = np.zeros(int((n_bars * bar + 2.5) * SR), dtype=np.float32)
    lead = {"mallet": mallet, "box": music_box, "pluck": pluck}[cfg["lead"]]
    for bar_i in range(n_bars):
        t0 = bar_i * bar
        deg = prog[bar_i % len(prog)]
        ch = chord(deg)
        cycle = bar_i // 8
        ph = tune[(bar_i // 2) % 4]
        for start, length, midi in ph:
            if int(start // 4) != bar_i % 2:
                continue
            m = midi + (12 if (cycle % 2 == 1 and cfg["lead"] != "box") else 0)
            _add(buf, lead(freq(m), min(1.8, length * beat + 0.5)), t0 + (start % 4) * beat, 0.30)
        if mood == "calm":
            _add(buf, pad([freq(n - 12) for n in ch], bar + 0.3), t0, 0.13)
            _add(buf, bass(freq(ch[0] - 24), bar * 0.9), t0, 0.16)
        else:
            order = [0, 1, 2, 1, 0, 2, 1, 2] if bar_i % 2 == 0 else [0, 2, 1, 2, 0, 1, 2, 1]
            for i, k in enumerate(order):
                _add(buf, pluck(freq(ch[k]), 0.5), t0 + i * beat / 2, 0.085)
            _add(buf, bass(freq(ch[0] - 24), beat * 1.6), t0, 0.22)
            _add(buf, bass(freq(ch[0] - 24 + 7), beat * 1.2), t0 + 2 * beat, 0.15)
            if cfg["perc"]:
                for i in range(8):
                    _add(buf, shaker(0.06, seed + i), t0 + i * beat / 2, 0.035 if i % 2 else 0.02)
            if cfg["kick"]:
                _add(buf, kick(), t0, 0.26)
                _add(buf, kick(), t0 + 2 * beat, 0.2)

    n = int(duration * SR)
    out = buf[:n].copy()
    # resolve: ring a tonic chord under the last 1.6 s and fade out
    tail = min(n, int(1.6 * SR))
    end_chord = pad([freq(root - 12), freq(root + 4 - 12), freq(root + 7 - 12), freq(root)], 1.6)[:tail]
    out[n - tail:] = out[n - tail:] * np.linspace(1, 0.15, tail, dtype=np.float32) + end_chord * 0.16
    fade = min(n, int(0.5 * SR))
    out[n - fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    out[: int(0.05 * SR)] *= np.linspace(0, 1, int(0.05 * SR), dtype=np.float32)
    peak = float(np.max(np.abs(out))) or 1.0
    out = out / peak * 0.6 * cfg["level"]
    info = {"seed": seed, "mood": mood, "tempo_bpm": tempo, "key_root_midi": root, "progression": prog,
            "bar_seconds": round(bar, 4), "origin": "composed and synthesized in-house (wonderland.audio.synth.compose)"}
    return out.astype(np.float32), info


def tempo_for(seed: int, mood: str) -> tuple[int, float]:
    """The tempo ``compose`` will pick for this seed (so songs can be written on the bar grid first)."""
    tempo = random.Random(seed).randint(*MOODS.get(mood, MOODS["bright"])["tempo"])
    return tempo, 4 * 60.0 / tempo


# ------------------------------------------------------------------ sound effects ----
def sfx_pop() -> np.ndarray:
    t = _t(0.11)
    f = 380 + 900 * t / 0.11
    return (np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-t * 26)).astype(np.float32)


def sfx_ding() -> np.ndarray:
    t = _t(0.9)
    x = np.sin(2 * math.pi * 1318 * t) * np.exp(-t * 5) + 0.4 * np.sin(2 * math.pi * 2637 * t) * np.exp(-t * 9)
    return (x * np.minimum(1, t * 500)).astype(np.float32)


def sfx_sparkle(seed: int = 1) -> np.ndarray:
    buf = np.zeros(int(0.9 * SR), dtype=np.float32)
    for i, m in enumerate([84, 88, 91, 96, 100]):
        _add(buf, mallet(freq(m), 0.5), i * 0.07, 0.5)
    return buf


def sfx_whoosh() -> np.ndarray:
    n = int(0.42 * SR)
    rng = np.random.default_rng(3)
    x = rng.standard_normal(n).astype(np.float32)
    k = 48
    x = np.convolve(x, np.ones(k, dtype=np.float32) / k, mode="same")
    env = np.sin(np.linspace(0, math.pi, n)) ** 2
    return (x * env * 3.0).astype(np.float32)


def sfx_boing() -> np.ndarray:
    t = _t(0.34)
    f = 220 + 260 * np.sin(np.minimum(1, t / 0.3) * math.pi)
    return (np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-t * 7) * np.minimum(1, t * 200)).astype(np.float32)


def sfx_tick() -> np.ndarray:
    t = _t(0.09)
    return (np.sin(2 * math.pi * 900 * t) * np.exp(-t * 60) + 0.5 * np.sin(2 * math.pi * 1800 * t) * np.exp(-t * 90)).astype(np.float32)


def sfx_splash() -> np.ndarray:
    n = int(0.5 * SR)
    rng = np.random.default_rng(5)
    x = np.diff(rng.standard_normal(n).astype(np.float32), prepend=0)
    x = np.convolve(x, np.ones(6, dtype=np.float32) / 6, mode="same")
    return (x * np.exp(-np.arange(n) / SR * 9) * 0.9).astype(np.float32)


def sfx_chime() -> np.ndarray:
    buf = np.zeros(int(1.3 * SR), dtype=np.float32)
    for i, m in enumerate([72, 76, 79, 84]):
        _add(buf, music_box(freq(m), 1.0), i * 0.11, 0.5)
    return buf


def sfx_twinkle() -> np.ndarray:
    buf = np.zeros(int(1.2 * SR), dtype=np.float32)
    for i, m in enumerate([91, 96, 93, 98]):
        _add(buf, music_box(freq(m), 0.8), i * 0.18, 0.35)
    return buf


SFX = {"pop": sfx_pop, "ding": sfx_ding, "sparkle": sfx_sparkle, "whoosh": sfx_whoosh, "boing": sfx_boing,
       "tick": sfx_tick, "splash": sfx_splash, "chime": sfx_chime, "twinkle": sfx_twinkle}
SFX_GAIN = {"pop": 0.30, "ding": 0.22, "sparkle": 0.20, "whoosh": 0.16, "boing": 0.24, "tick": 0.25, "splash": 0.22,
            "chime": 0.22, "twinkle": 0.16}


def mix_episode(duration: float, voices: list[tuple[float, np.ndarray]], music: np.ndarray | None,
                sfx: list[tuple[float, str]]) -> np.ndarray:
    """Mix voice clips, ducked music and effects into one mono track of exactly ``duration`` seconds."""
    n = int(duration * SR)
    voice = np.zeros(n, dtype=np.float32)
    for at, clip in voices:
        _add(voice, clip, at, 1.0)
    out = voice.copy()
    if music is not None and len(music):
        m = np.zeros(n, dtype=np.float32)
        m[: min(n, len(music))] = music[:n]
        act = np.abs(voice)
        win = int(0.18 * SR)
        act = np.convolve(act, np.ones(win, dtype=np.float32) / win, mode="same")
        act = np.clip(act / 0.035, 0, 1)
        act = np.convolve(act, np.ones(win, dtype=np.float32) / win, mode="same")
        out += m * (0.62 - 0.40 * act)             # duck the band under speech
    for at, name in sfx:
        fn = SFX.get(name)
        if fn:
            _add(out, fn(), at, SFX_GAIN.get(name, 0.2))
    peak = float(np.max(np.abs(out))) or 1.0
    if peak > 0.97:
        out = out / peak * 0.97
    return out
