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

SR = 48000          # session/mix rate; voice clips (44.1 kHz) are converted on import with ``resample``
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




# ------------------------------------------------------------------ DSP helpers ------
def _fast_len(n: int) -> int:
    return 1 << max(1, (n - 1).bit_length())


def shaped_noise(n: int, seed: int, lo: float, hi: float, tilt: float = 0.0) -> np.ndarray:
    """Band-limited noise built in the frequency domain (unit RMS).

    Because it is an inverse FFT of exactly ``n`` samples it is periodic in ``n``: a
    buffer made this way loops with no seam, which is what the ambience beds rely on.
    ``tilt`` > 0 darkens it (power falls as 1/f**tilt)."""
    rng = np.random.default_rng(seed)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    fs = np.maximum(f, 1.0)
    mag = 1.0 / (1.0 + (lo / fs) ** 4) / (1.0 + (fs / hi) ** 4)       # 4th-order-ish skirts, no hard edges
    if tilt:
        mag = mag * fs ** (-tilt / 2.0)
    mag[0] = 0.0
    spec = mag * np.exp(1j * rng.uniform(0, 2 * math.pi, len(f)))
    x = np.fft.irfft(spec, n)
    return (x / (float(np.sqrt(np.mean(x * x))) or 1.0)).astype(np.float32)


def bandlimit(x: np.ndarray, lo: float = 40.0, hi: float = 9000.0) -> np.ndarray:
    """Zero-phase rumble and harshness trim (gentle skirts) for the non-voice layers."""
    n = len(x)
    m = _fast_len(n)
    f = np.maximum(np.fft.rfftfreq(m, 1.0 / SR), 1.0)
    resp = 1.0 / np.sqrt(1.0 + (lo / f) ** 4) / np.sqrt(1.0 + (f / hi) ** 6)
    return np.fft.irfft(np.fft.rfft(x, m) * resp, m)[:n].astype(np.float32)


def resample(x: np.ndarray, src: int, dst: int, taps: int = 24) -> np.ndarray:
    """Polyphase windowed-sinc sample-rate conversion (numpy only). Used to bring the
    44.1 kHz voice clips into the 48 kHz session without the dulling of linear interpolation."""
    if src == dst or len(x) == 0:
        return x.astype(np.float32)
    g = math.gcd(src, dst)
    L, M = dst // g, src // g
    fc = 0.5 / max(L, M) * 0.92
    k = np.arange(-taps * L, taps * L + 1)
    h = 2 * fc * np.sinc(2 * fc * k) * np.kaiser(len(k), 9.0) * L
    n_out = int(len(x) * L // M)
    pos = np.arange(n_out, dtype=np.int64) * M
    base, phase = pos // L, pos % L
    xp = np.concatenate([np.zeros(taps + 1, np.float32), x.astype(np.float32), np.zeros(taps + 2, np.float32)])
    out = np.zeros(n_out, dtype=np.float32)
    hf = h.astype(np.float32)
    for j in range(-taps, taps + 1):                      # tap j reads x[base - j] with weight h[phase + j*L]
        idx = phase + j * L + taps * L
        ok = (idx >= 0) & (idx < len(hf))
        w = np.where(ok, hf[np.clip(idx, 0, len(hf) - 1)], 0.0)
        out += w * xp[base - j + taps + 1]
    return out


def pitch_shift(x: np.ndarray, semitones: float) -> np.ndarray:
    """Tape-style pitch change (shorter when pitched up) — fine for one-shot effects."""
    r = 2 ** (semitones / 12.0)
    n = max(1, int(len(x) / r))
    return np.interp(np.arange(n) * r, np.arange(len(x)), x).astype(np.float32)


def exaggerate(x: np.ndarray, semitones: float = 2.0, level: float = 0.2) -> np.ndarray:
    """Cartoon exaggeration: the hit plus a copy pitched up ``semitones`` at ``level``."""
    y = x.astype(np.float32).copy()
    up = pitch_shift(x, semitones)
    y[: len(up)] += level * up
    return y


def _norm(x: np.ndarray) -> np.ndarray:
    return (x / (float(np.max(np.abs(x))) or 1.0)).astype(np.float32)


def _ar(n: int, attack: float, decay_rate: float) -> np.ndarray:
    """Soft attack (never a click) then exponential decay, with a short fade at the very end."""
    t = np.arange(n) / SR
    env = np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-np.maximum(0.0, t - attack) * decay_rate)
    tail = min(n, int(0.008 * SR))
    env[n - tail:] *= np.linspace(1, 0, tail)
    return env.astype(np.float32)


def _hann(n: int) -> np.ndarray:
    return (np.sin(np.linspace(0, math.pi, n)) ** 2).astype(np.float32)


def _glide(f0: float, f1: float, dur: float, curve: float = 1.0) -> np.ndarray:
    t = _t(dur)
    f = f0 + (f1 - f0) * (t / max(dur, 1e-6)) ** curve
    return np.sin(2 * math.pi * np.cumsum(f) / SR).astype(np.float32)


# ------------------------------------------------------------------ Foley sounds -----
# Every Foley sound is filtered noise and/or a sine "body": soft attack (>= 3 ms), nothing above
# ~6 kHz, nothing below ~55 Hz. ``v`` picks one of a few takes so repeated steps do not sound stamped.
SURFACES = ("grass", "wood", "tile", "water", "rug")
_STEP = {  # noise band, noise decay, body (f0 -> f1), body level, length
    "grass": (350, 2600, 38, (120, 85), 0.35, 0.14),
    "wood": (450, 1900, 60, (175, 120), 0.9, 0.15),
    "tile": (900, 4200, 75, (330, 260), 0.6, 0.11),
    "water": (500, 3800, 16, (140, 90), 0.3, 0.26),
    "rug": (180, 950, 34, (110, 80), 0.45, 0.14),
}


def fol_footstep(surface: str = "grass", v: int = 0) -> np.ndarray:
    lo, hi, dec, (f0, f1), body, dur = _STEP.get(surface, _STEP["grass"])
    n = int(dur * SR)
    x = shaped_noise(n, 100 + 7 * v + SURFACES.index(surface if surface in SURFACES else "grass"), lo * (1 + 0.06 * v), hi, 0.6) * _ar(n, 0.004, dec) * 0.5
    x += body * _glide(f0 * (1 + 0.04 * v), f1, dur) * _ar(n, 0.005, 34)
    if surface == "water":                                   # a little "plip" on top of the wet step
        b = _glide(520 + 60 * v, 980 + 80 * v, 0.07) * _ar(int(0.07 * SR), 0.006, 30)
        x[int(0.02 * SR): int(0.02 * SR) + len(b)] += 0.35 * b
    return _norm(x)


def fol_thump(surface: str = "grass", v: int = 0) -> np.ndarray:
    """Landing: a round, low 'bmp' plus the surface's own step. Soft 7 ms attack."""
    n = int(0.3 * SR)
    x = _glide(98 + 5 * v, 62, 0.3, 0.5) * _ar(n, 0.007, 17)
    step = fol_footstep(surface, v)
    x[: len(step)] += 0.55 * step
    return _norm(x)


def fol_clap(v: int = 0) -> np.ndarray:
    n = int(0.13 * SR)
    x = np.zeros(n, dtype=np.float32)
    for k, at in enumerate((0.0, 0.009)):                    # two palms never land in the same millisecond
        m = n - int(at * SR)
        x[int(at * SR):] += shaped_noise(m, 300 + 5 * v + k, 750, 3200, 0.3) * _ar(m, 0.003, 46) * (1.0 if k == 0 else 0.6)
    x += 0.25 * np.sin(2 * math.pi * (880 + 40 * v) * np.arange(n) / SR).astype(np.float32) * _ar(n, 0.003, 60)
    return _norm(x)


def fol_swish(v: int = 0) -> np.ndarray:
    n = int((0.17 + 0.02 * v) * SR)
    return _norm(shaped_noise(n, 400 + v, 600, 3400, 0.8) * _hann(n))


def fol_settle(v: int = 0) -> np.ndarray:
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    env = (np.minimum(1, t / 0.045) * np.exp(-np.maximum(0, t - 0.045) * 9)).astype(np.float32)
    env[-480:] *= np.linspace(1, 0, 480, dtype=np.float32)
    x = shaped_noise(n, 500 + v, 160, 1300, 1.0) * env
    x += 0.3 * _glide(84, 66, 0.45) * env
    return _norm(x)


def fol_brush(v: int = 0) -> np.ndarray:
    n = int(0.085 * SR)
    return _norm(shaped_noise(n, 600 + v, 2200, 5600, 0.2) * _hann(n))


def fol_wash(v: int = 0) -> np.ndarray:
    n = int(0.17 * SR)
    x = shaped_noise(n, 700 + v, 550, 3200, 0.7) * _hann(n) * 0.8
    b = _glide(620 + 90 * v, 1250 + 60 * v, 0.045) * _hann(int(0.045 * SR))
    x[int(0.05 * SR): int(0.05 * SR) + len(b)] += 0.4 * b
    return _norm(x)


def fol_pat(v: int = 0) -> np.ndarray:
    """Something light (a leaf, a petal) touching the ground."""
    n = int(0.07 * SR)
    return _norm(shaped_noise(n, 800 + v, 800, 3200, 0.6) * _ar(n, 0.003, 55))


def fol_give(v: int = 0) -> np.ndarray:
    """Soft whoosh as a toy leaves a hand."""
    n = int(0.3 * SR)
    return _norm(shaped_noise(n, 900 + v, 320, 2100, 1.0) * _hann(n))


def fol_catch(v: int = 0) -> np.ndarray:
    n = int(0.16 * SR)
    x = _glide(250, 205, 0.16) * _ar(n, 0.005, 26) + 0.3 * shaped_noise(n, 950 + v, 500, 2400, 0.6) * _ar(n, 0.004, 50)
    return _norm(x)


def fol_pop_in(v: int = 0) -> np.ndarray:
    """A prop popping into view: the house 'pop', rounded (soft attack, a little lower)."""
    t = _t(0.12)
    f = (340 + 30 * v) + 780 * t / 0.12
    return _norm(np.sin(2 * math.pi * np.cumsum(f) / SR) * np.exp(-t * 24) * np.minimum(1, t / 0.004))


def sfx_drip() -> np.ndarray:
    buf = np.zeros(int(0.4 * SR), dtype=np.float32)
    d = _glide(880, 1700, 0.06, 0.6) * _ar(int(0.06 * SR), 0.004, 40)
    _add(buf, d, 0.0, 1.0)
    _add(buf, d, 0.14, 0.25)
    return buf


def sfx_slide(up: bool = True, dur: float = 0.34) -> np.ndarray:
    """Slide whistle: a sine glide with a touch of breath and vibrato."""
    t = _t(dur)
    a, b = (480, 1050) if up else (1050, 480)
    f = a + (b - a) * (t / dur) ** (0.8 if up else 1.2) + 9 * np.sin(2 * math.pi * 6.5 * t)
    x = np.sin(2 * math.pi * np.cumsum(f) / SR) + 0.18 * np.sin(4 * math.pi * np.cumsum(f) / SR)
    x = x * _hann(len(t)) ** 0.6 + 0.04 * shaped_noise(len(t), 41, 1500, 5000) * _hann(len(t))
    return _norm(x)


def sfx_slide_up() -> np.ndarray:
    return sfx_slide(True)


def sfx_slide_down() -> np.ndarray:
    return sfx_slide(False)


def sfx_rattle() -> np.ndarray:
    buf = np.zeros(int(0.5 * SR), dtype=np.float32)
    for i in range(6):
        n = int(0.05 * SR)
        _add(buf, shaped_noise(n, 60 + i, 1800, 5200, 0.2) * _ar(n, 0.003, 70), i * 0.07, 0.8 if i % 2 == 0 else 0.5)
    return _norm(buf)


SFX.update({"drip": sfx_drip, "slide_up": sfx_slide_up, "slide_down": sfx_slide_down, "rattle": sfx_rattle,
            "thump": fol_thump, "clap": fol_clap, "swish": fol_swish})
SFX_GAIN.update({"drip": 0.14, "slide_up": 0.10, "slide_down": 0.10, "rattle": 0.10, "thump": 0.18, "clap": 0.10, "swish": 0.06})

# Foley library: name -> (function, takes surface?). Gains live with the events (wonderland.audio.foley).
FOLEY = {"footstep": (fol_footstep, True), "thump": (fol_thump, True), "clap": (fol_clap, False), "swish": (fol_swish, False),
         "settle": (fol_settle, False), "brush": (fol_brush, False), "wash": (fol_wash, False), "pat": (fol_pat, False),
         "give": (fol_give, False), "catch": (fol_catch, False), "pop_in": (fol_pop_in, False),
         "slide_up": (lambda v=0: sfx_slide(True, 0.26), False), "sparkle": (lambda v=0: _norm(sfx_sparkle()), False)}
_cache: dict = {}


def foley_sound(name: str, surface: str = "grass", variant: int = 0, exaggeration: tuple[float, float] = (2.0, 0.2)) -> np.ndarray:
    """One Foley hit, band-limited, with its cartoon layer (+2 semitones at 20 %) already mixed in. Cached."""
    key = (name, surface if FOLEY[name][1] else "", variant % 3, exaggeration)
    if key not in _cache:
        fn, surf = FOLEY[name]
        x = fn(surface, variant % 3) if surf else fn(variant % 3)
        x = bandlimit(np.concatenate([x, np.zeros(256, np.float32)]), 55, 6500)
        _cache[key] = exaggerate(x, *exaggeration) if exaggeration[1] else x
    return _cache[key]


def sfx_sound(name: str) -> np.ndarray | None:
    """A hard effect from ``SFX``, rounded for small ears: 3 ms fade-in, rumble/harshness trimmed. Cached."""
    key = ("sfx", name)
    if key not in _cache:
        fn = SFX.get(name)
        if fn is None:
            return None
        x = np.concatenate([fn().astype(np.float32), np.zeros(256, np.float32)])
        k = int(0.003 * SR)
        x[:k] *= np.linspace(0, 1, k, dtype=np.float32)
        _cache[key] = bandlimit(x, 60, 7500)
    return _cache[key]


# ------------------------------------------------------------------ ambience ---------
AMBIENCE = {  # env -> (description, level in dBFS RMS before the bus gain)
    "meadow": ("light breeze in the grass, a few songbirds", -45.0),
    "garden": ("soft breeze, songbirds close by", -45.0),
    "pond": ("gentle water lapping, small plips, a distant bird", -45.0),
    "hilltop": ("open-air wind, one far bird", -46.0),
    "forest": ("leaves rustling overhead, woodland birds", -45.0),
    "rainy": ("steady soft rain with small drops", -43.0),
    "night": ("crickets and a very soft night breeze", -47.0),
    "playroom": ("quiet warm room tone", -52.0),
    "bathroom": ("quiet tiled room tone with an occasional water drip", -51.0),
    "bedroom": ("very quiet room tone, crickets far outside the window", -53.0),
}
AMB_LOOP_SECONDS = 12.0


def _slow(n: int, rng: random.Random, depth: float, cycles=(1, 2, 3, 5)) -> np.ndarray:
    """Slow amplitude movement made of whole cycles per loop, so the loop point stays seamless."""
    t = np.arange(n) / n
    m = np.zeros(n)
    for c in cycles:
        m += rng.uniform(0.4, 1.0) * np.sin(2 * math.pi * (c * t + rng.random()))
    return (1.0 + depth * m / len(cycles) * 1.6).clip(0.15, None)


def _place(buf: np.ndarray, x: np.ndarray, at: float, gain: float, pan: float) -> None:
    """Add a small sound into a stereo loop, wrapping around the end (keeps the loop seamless)."""
    n = buf.shape[1]
    idx = (int(at * SR) + np.arange(len(x))) % n
    a = (pan + 1) * math.pi / 4
    np.add.at(buf[0], idx, x * gain * math.cos(a))
    np.add.at(buf[1], idx, x * gain * math.sin(a))


def _bird(rng: random.Random, low: float = 2300, high: float = 4300) -> np.ndarray:
    """A short phrase of 2-4 soft chirps (sine glides)."""
    out = np.zeros(int(0.9 * SR), dtype=np.float32)
    f = rng.uniform(low, high)
    at = 0.0
    for _ in range(rng.randint(2, 4)):
        d = rng.uniform(0.06, 0.13)
        f2 = f * rng.choice([0.82, 0.9, 1.12, 1.22])
        c = _glide(f, f2, d) * _hann(int(d * SR))
        _add(out, c, at, rng.uniform(0.6, 1.0))
        at += d + rng.uniform(0.04, 0.12)
        f = min(high, max(low, f2 * rng.choice([0.95, 1.05])))
    return out


def _cricket(freq: float) -> np.ndarray:
    out = np.zeros(int(0.12 * SR), dtype=np.float32)
    for i in range(3):
        n = int(0.02 * SR)
        _add(out, np.sin(2 * math.pi * freq * np.arange(n) / SR).astype(np.float32) * _hann(n), i * 0.03, 1.0)
    return out


def _diffuse(n: int, seed: int, lo: float, hi: float, tilt: float) -> np.ndarray:
    """Stereo noise bed: the two channels share a little and differ a lot (decorrelated, mono-safe)."""
    mid = shaped_noise(n, seed, lo, hi, tilt)
    return np.stack([0.45 * mid + shaped_noise(n, seed + 1, lo, hi, tilt), 0.45 * mid + shaped_noise(n, seed + 2, lo, hi, tilt)])


def ambience_loop(env: str, seed: int = 0, seconds: float = AMB_LOOP_SECONDS) -> np.ndarray:
    """A seamless stereo ambience loop for one environment, shape (2, n). Deterministic from (env, seed)."""
    key = ("amb", env, seed, seconds)
    if key in _cache:
        return _cache[key]
    if env not in AMBIENCE:
        env = "playroom"
    n = int(seconds * SR)
    rng = random.Random(f"{env}:{seed}")
    s = rng.randrange(1 << 30)
    buf = np.zeros((2, n), dtype=np.float64)

    def birds(count: int, level: float, low=2300, high=4300):
        for _ in range(count):
            _place(buf, _bird(rng, low, high), rng.uniform(0, seconds), level * rng.uniform(0.6, 1.0), rng.uniform(-0.8, 0.8))

    if env in ("meadow", "garden", "hilltop"):
        wind = {"meadow": (180, 1300, 1.6, 0.35), "garden": (220, 1500, 1.5, 0.25), "hilltop": (120, 950, 1.9, 0.5)}[env]
        buf += _diffuse(n, s, wind[0], wind[1], wind[2]) * _slow(n, rng, wind[3])
        birds({"meadow": 5, "garden": 7, "hilltop": 2}[env], {"meadow": 1.3, "garden": 1.5, "hilltop": 0.8}[env])
    elif env == "pond":
        buf += _diffuse(n, s, 300, 2400, 1.2) * _slow(n, rng, 0.45, (4, 7, 9, 11)) * 0.9
        for _ in range(6):
            f = rng.uniform(380, 700)
            _place(buf, _glide(f, f * 1.9, 0.07) * _ar(int(0.07 * SR), 0.006, 30), rng.uniform(0, seconds), 1.6, rng.uniform(-0.7, 0.7))
        birds(2, 0.9)
    elif env == "forest":
        rustle = np.abs(shaped_noise(n, s + 9, 0.6, 3.0)) ** 1.5                 # slow, irregular (still periodic) swell
        buf += _diffuse(n, s, 900, 5200, 0.9) * (0.35 + rustle / float(np.max(rustle))) + 0.5 * _diffuse(n, s + 20, 150, 800, 1.6)
        birds(4, 1.2, 1900, 3600)
    elif env == "rainy":
        buf += _diffuse(n, s, 700, 6200, 0.8) * _slow(n, rng, 0.12)
        for _ in range(170):
            d = rng.uniform(0.012, 0.03)
            f = rng.uniform(1400, 4200)
            _place(buf, _glide(f, f * 0.8, d) * _ar(int(d * SR), 0.003, 120), rng.uniform(0, seconds), rng.uniform(0.8, 2.2), rng.uniform(-1, 1))
    elif env == "night":
        buf += 0.35 * _diffuse(n, s, 150, 900, 1.8) * _slow(n, rng, 0.3)
        for freq, pan, period, lvl in ((4150, -0.55, seconds / 21, 1.0), (4480, 0.5, seconds / 17, 0.7)):
            c = _cricket(freq)
            at = rng.uniform(0, period)
            while at < seconds - 1e-6:
                _place(buf, c, at, lvl * 0.5, pan)
                at += period
    else:  # indoor room tone
        buf += _diffuse(n, s, 90, 520, 2.0) * _slow(n, rng, 0.1)
        if env == "bathroom":
            for _ in range(2):
                _place(buf, sfx_drip(), rng.uniform(0, seconds), 2.2, rng.uniform(-0.4, 0.4))
        if env == "bedroom":
            c = _cricket(4300)
            for i in range(12):
                _place(buf, c, i * seconds / 12 + 0.3, 0.12, 0.6)
    rms = float(np.sqrt(np.mean(buf * buf))) or 1.0
    out = (buf / rms * 10 ** (AMBIENCE[env][1] / 20)).astype(np.float32)
    _cache[key] = out
    return out


def ambience_track(segments: list[tuple[float, float, str]], duration: float, seed: int = 0, crossfade: float = 0.6) -> np.ndarray:
    """Stereo ambience for the whole episode. ``segments`` = (start, end, env) per shot; neighbouring shots in
    the same place are merged, a change of place is an equal-power cross-fade centred on the cut."""
    n = int(duration * SR)
    out = np.zeros((2, n), dtype=np.float32)
    merged: list[list] = []
    for a, b, env in segments:
        if merged and merged[-1][2] == env:
            merged[-1][1] = b
        else:
            merged.append([a, b, env])
    h = crossfade / 2
    for i, (a, b, env) in enumerate(merged):
        i0 = max(0, int((a - (h if i else 0)) * SR))
        i1 = min(n, int((b + (h if i < len(merged) - 1 else 0)) * SR))
        if i1 <= i0:
            continue
        loop = ambience_loop(env, seed)
        idx = np.arange(i0, i1) % loop.shape[1]
        g = np.ones(i1 - i0, dtype=np.float32)
        k = min(int(crossfade * SR), i1 - i0)
        if i:
            g[:k] *= np.sin(np.linspace(0, math.pi / 2, k)).astype(np.float32)
        if i < len(merged) - 1:
            g[-k:] *= np.cos(np.linspace(0, math.pi / 2, k)).astype(np.float32)
        out[:, i0:i1] += loop[:, idx] * g
    f = min(n, int(0.4 * SR))
    out[:, :f] *= np.linspace(0, 1, f, dtype=np.float32)
    out[:, n - f:] *= np.linspace(1, 0, f, dtype=np.float32)
    return out


# ------------------------------------------------------------------ stings -----------
def sting(root_midi: int, kind: str = "title") -> np.ndarray:
    """A short musical motif in the episode's key: rising for the title card, resolving for the end card."""
    buf = np.zeros(int(2.0 * SR), dtype=np.float32)
    if kind == "title":
        for i, st in enumerate((0, 4, 7, 12)):
            _add(buf, mallet(freq(root_midi + 12 + st), 0.8), i * 0.1, 0.5 if i < 3 else 0.62)
        _add(buf, music_box(freq(root_midi + 24 + 4), 0.9), 0.3, 0.16)
    else:
        for i, st in enumerate((7, 4, 2, 0)):
            _add(buf, music_box(freq(root_midi + 12 + st), 1.2), i * 0.16, 0.5)
        _add(buf, pad([freq(root_midi), freq(root_midi + 4), freq(root_midi + 7)], 1.4), 0.48, 0.3)
    return _norm(buf) * 0.9


# ------------------------------------------------------------------ dynamics ---------
CTRL = 240                     # control-rate hop for envelopes (5 ms at 48 kHz)


def follow(x: np.ndarray, attack: float, release: float, lookahead: float = 0.0) -> np.ndarray:
    """Peak envelope follower with separate attack/release, computed at control rate and returned at
    audio rate. ``lookahead`` moves the envelope earlier so a gain change is already there when the sound starts."""
    n = len(x)
    nb = -(-n // CTRL)
    pk = np.abs(np.pad(x, (0, nb * CTRL - n))).reshape(nb, CTRL).max(axis=1)
    dt = CTRL / SR
    ca, cr = math.exp(-dt / max(attack, 1e-4)), math.exp(-dt / max(release, 1e-4))
    env = np.empty(nb)
    e = 0.0
    for i, p in enumerate(pk.tolist()):
        c = ca if p > e else cr
        e = p + (e - p) * c
        env[i] = e
    if lookahead > 0:
        sh = int(round(lookahead / dt))
        env = np.concatenate([env[sh:], np.full(sh, env[-1])])
        env = np.maximum(env, np.concatenate([env[:1], env[:-1]]))
    return np.interp(np.arange(n), (np.arange(nb) + 0.5) * CTRL, env).astype(np.float32)


def pan_gains(pan: float) -> tuple[float, float]:
    """Constant-power pan, -1 (left) .. +1 (right)."""
    a = (max(-1.0, min(1.0, pan)) + 1) * math.pi / 4
    return math.cos(a), math.sin(a)


def limit(x: np.ndarray, ceiling: float = 0.7) -> tuple[np.ndarray, float]:
    """Look-ahead peak limiter for a (2, n) mix: transparent below the ceiling, smooth 5 ms / 120 ms gain
    moves above it. Returns (limited, deepest gain reduction in dB)."""
    n = x.shape[1]
    blk = 48
    nb = -(-n // blk)
    pk = np.abs(np.pad(x, ((0, 0), (0, nb * blk - n)))).max(axis=0).reshape(nb, blk).max(axis=1)
    g = np.minimum(1.0, ceiling / np.maximum(pk, 1e-9))
    if float(g.min()) >= 1.0:
        return x, 0.0
    w = 6                                                      # 6 ms look-ahead and hold
    gp = np.pad(g, (w, w), constant_values=1.0)
    g = np.min(np.stack([gp[i:i + nb] for i in range(2 * w + 1)]), axis=0)
    rel = math.exp(-(blk / SR) / 0.12)
    out = np.empty(nb)
    e = 1.0
    for i, v in enumerate(g.tolist()):                         # instant down (already held), slow recovery
        e = v if v < e else v + (e - v) * rel
        out[i] = e
    ker = np.ones(2 * w + 1) / (2 * w + 1)
    sm = np.minimum(out, np.convolve(np.pad(out, (w, w), mode="edge"), ker, mode="valid"))
    gain = np.interp(np.arange(n), np.arange(nb) * blk, np.minimum(sm, np.concatenate([sm[1:], sm[-1:]])),).astype(np.float32)
    y = x * gain
    over = float(np.max(np.abs(y)))
    if over > ceiling:
        y = y * (ceiling / over)
    return y.astype(np.float32), round(20 * math.log10(max(float(gain.min()), 1e-6)), 2)


# ------------------------------------------------------------------ metering ---------
def _k_weight(f: np.ndarray) -> np.ndarray:
    """|H|^2 of the ITU-R BS.1770 K-weighting (the 48 kHz reference biquads, evaluated at frequency f)."""
    z = np.exp(-2j * math.pi * f / 48000.0)
    shelf = (1.53512485958697 - 2.69169618940638 * z + 1.19839281085285 * z * z) / (1 - 1.69065929318241 * z + 0.73248077421585 * z * z)
    hp = (1 - 2 * z + z * z) / (1 - 1.99004745483398 * z + 0.99007225036621 * z * z)
    return np.abs(shelf * hp) ** 2


def analyse(x: np.ndarray) -> dict:
    """Level and spectrum facts about a mono (n,) or stereo (2, n) buffer, numpy only.

    ``lufs`` follows BS.1770 (K-weighting applied per 400 ms block in the frequency domain, 75 % overlap,
    absolute -70 and relative -10 LU gates). ``above_8k_pct`` / ``below_40_pct`` are shares of total energy."""
    x = np.atleast_2d(np.asarray(x, dtype=np.float32))
    n = x.shape[1]
    peak = float(np.max(np.abs(x))) if n else 0.0
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if n else 0.0
    out = {"peak_dbfs": _db(peak), "rms_dbfs": _db(rms), "crest_db": round(_db(peak) - _db(rms), 2) if rms > 0 else None,
           "lufs": None, "above_8k_pct": 0.0, "below_40_pct": 0.0}
    B, hop = int(0.4 * SR), int(0.1 * SR)
    if n < B or rms == 0:
        return out
    f = np.fft.rfftfreq(B, 1.0 / SR)
    kw = _k_weight(f)
    starts = np.arange(0, n - B + 1, hop)
    z = np.zeros(len(starts))
    band = np.zeros(3)                                         # total, >8 kHz, <40 Hz (plain energy)
    for ch in x:
        for i in range(0, len(starts), 64):
            blk = np.stack([ch[s:s + B] for s in starts[i:i + 64]])
            p = np.abs(np.fft.rfft(blk, axis=1)) ** 2
            p[:, 1:-1] *= 2
            z[i:i + 64] += (p * kw).sum(axis=1) / (B * B)
            tot = p.sum(axis=0)
            band += [tot.sum(), tot[f > 8000].sum(), tot[(f < 40)].sum()]
    with np.errstate(divide="ignore"):
        l = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    keep = l > -70
    if keep.any():
        rel = -0.691 + 10 * math.log10(float(z[keep].mean())) - 10
        keep &= l > rel
        out["lufs"] = round(-0.691 + 10 * math.log10(float(z[keep].mean())), 2)
    if band[0] > 0:
        out["above_8k_pct"] = round(100 * band[1] / band[0], 3)
        out["below_40_pct"] = round(100 * band[2] / band[0], 3)
    return out


def _db(v: float) -> float:
    return round(20 * math.log10(v), 2) if v > 0 else -120.0


# ------------------------------------------------------------------ the mix ----------
BUS_GAIN = {"voice": 1.0, "music": 0.60, "ambience": 1.0, "foley": 1.0, "sfx": 0.80}
MIX = {
    "music_under_voice_db": -13.0,     # how far the tune drops while someone speaks
    "music_under_fx_db": -6.0,         # side-chain dip under Foley / effect peaks
    "fx_under_voice_db": -8.0,         # Foley and effects step back a little under speech too
    "ambience_under_voice_db": -3.0,
    "fx_ref": 0.05,                    # Foley/SFX envelope level that gives the full side-chain dip
    "target_lufs": -14.0,
    "ceiling": 0.708,                  # -3 dBFS sample peak: head-room for AAC overshoot (true peak <= -1.5 dBTP after encode)
    "max_pan": 0.5,
}


def mix_layers(duration: float, voices: list[tuple[float, np.ndarray]], music: np.ndarray | None = None,
               sfx: list[dict] | None = None, foley: list[dict] | None = None, ambience: np.ndarray | None = None,
               stings: list[tuple[float, np.ndarray]] | None = None, master: bool = True,
               exaggeration: tuple[float, float] = (2.0, 0.2)) -> dict:
    """Mix the five buses to stereo at 48 kHz.

    voices   [(start seconds, mono clip at SR)]           -> centre, full level, never ducked
    music    mono tune (ducks under the voice and, about 6 dB, under Foley/SFX peaks)
    sfx      [{"t", "name", "gain"?, "pan"?}]             hard effects from ``SFX``
    foley    [{"t", "sound", "surface"?, "gain", "pan", "variant"?}]  hits from ``FOLEY`` (cartoon layer added)
    ambience (2, n) stereo bed; stings [(start, mono)] ride on the music bus (voice duck only)

    Returns {"mix": (2, n) float32, "stems": {bus: (2, n)}, "gains": {...curves...}, "master_gain_db", "limiter_db"}.
    """
    n = int(round(duration * SR))
    c = math.sqrt(0.5)
    voice = np.zeros(n, dtype=np.float32)
    for at, clip in voices:
        _add(voice, clip, at, 1.0)
    fx = {"foley": np.zeros((2, n), dtype=np.float32), "sfx": np.zeros((2, n), dtype=np.float32)}
    for e in foley or []:
        x = foley_sound(e["sound"], e.get("surface", "grass"), int(e.get("variant", 0)), exaggeration)
        l, r = pan_gains(float(e.get("pan", 0.0)) * MIX["max_pan"])
        _add(fx["foley"][0], x, e["t"], e["gain"] * l)
        _add(fx["foley"][1], x, e["t"], e["gain"] * r)
    for e in sfx or []:
        x = sfx_sound(e["name"])
        if x is None:
            continue
        g = e.get("gain", SFX_GAIN.get(e["name"], 0.2))
        l, r = pan_gains(float(e.get("pan", 0.0)) * MIX["max_pan"])
        _add(fx["sfx"][0], x, e["t"], g * l)
        _add(fx["sfx"][1], x, e["t"], g * r)
    fx["foley"] *= BUS_GAIN["foley"]
    fx["sfx"] *= BUS_GAIN["sfx"]

    # speech activity: 0..1, opens 60 ms before a line (so nothing masks the first consonant), closes over 0.35 s
    act = np.clip(follow(voice, 0.02, 0.35, lookahead=0.06) / 0.03, 0, 1) if voices else np.zeros(n, dtype=np.float32)
    act = act * act * (3 - 2 * act)

    def dip(db: float, k: np.ndarray) -> np.ndarray:
        return (10 ** (db / 20)) ** k                         # 0 -> unity, 1 -> full dip, smooth in dB

    g_fx = dip(MIX["fx_under_voice_db"], act)
    fx["foley"] *= g_fx
    fx["sfx"] *= g_fx
    side = np.clip(follow(np.abs(fx["foley"]).max(axis=0) + np.abs(fx["sfx"]).max(axis=0), 0.015, 0.45, lookahead=0.02) / MIX["fx_ref"], 0, 1)
    g_music = dip(MIX["music_under_voice_db"], act) * dip(MIX["music_under_fx_db"], side)
    stems = {"voice": np.stack([voice * c, voice * c]) * BUS_GAIN["voice"]}
    m = np.zeros(n, dtype=np.float32)
    if music is not None and len(music):
        k = min(n, len(music))
        m[:k] = bandlimit(music[:k], 45, 9000)
        m *= g_music
    if stings:
        st = np.zeros(n, dtype=np.float32)
        for at, x in stings:
            _add(st, x, at, 0.34)
        m += st * dip(MIX["music_under_voice_db"], act)
    stems["music"] = np.stack([m * c, m * c]) * BUS_GAIN["music"]
    amb = np.zeros((2, n), dtype=np.float32)
    if ambience is not None:
        k = min(n, ambience.shape[1])
        amb[:, :k] = ambience[:, :k]
        amb *= dip(MIX["ambience_under_voice_db"], act) * BUS_GAIN["ambience"]
    stems["ambience"] = amb
    stems.update(fx)
    mix = stems["voice"] + stems["music"] + stems["ambience"] + stems["foley"] + stems["sfx"]
    gain_db, lim_db = 0.0, 0.0
    if master:
        for _ in range(2):                                      # level to target, limit, re-check once
            lu = analyse(mix)["lufs"]
            if lu is None:
                break
            step = MIX["target_lufs"] - lu
            if abs(step) < 0.1:
                break
            gain_db += step
            mix, d = limit(mix * 10 ** (step / 20), MIX["ceiling"])
            lim_db = min(lim_db, d)
        mix, d = limit(mix, MIX["ceiling"])
        lim_db = min(lim_db, d)
    return {"mix": mix.astype(np.float32), "stems": stems, "gains": {"speech": act, "music": g_music, "fx_sidechain": side},
            "master_gain_db": round(gain_db, 2), "limiter_db": lim_db}


def mix_episode(duration: float, voices: list[tuple[float, np.ndarray]], music: np.ndarray | None,
                sfx: list[tuple[float, str]]) -> np.ndarray:
    """Legacy entry point: voice + ducked music + effects as one mono track (unmastered). ``mix_layers`` is the real desk."""
    out = mix_layers(duration, voices, music, [{"t": at, "name": name} for at, name in sfx], master=False)["mix"]
    mono = (out[0] + out[1]) * math.sqrt(0.5)
    peak = float(np.max(np.abs(mono))) or 1.0
    return mono / peak * 0.97 if peak > 0.97 else mono
