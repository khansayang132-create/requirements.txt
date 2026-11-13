"""Original music, ambience and Foley, synthesised locally with numpy, and the scene mix.

Nothing is downloaded or sampled: every sound is generated here, so licensing is clean. Footsteps are placed on the
exact frames where the animation plants a foot (cues from build_scene), dialogue on its line cue, and the music is
ducked under every line.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MOODS = {
    "warm": {"chords": [("C", "maj"), ("A", "min"), ("F", "maj"), ("G", "maj")], "bpm": 84, "bright": 0.6},
    "sad": {"chords": [("A", "min"), ("F", "maj"), ("D", "min"), ("E", "min")], "bpm": 66, "bright": 0.3},
    "joyful": {"chords": [("F", "maj"), ("G", "maj"), ("E", "min"), ("A", "min")], "bpm": 104, "bright": 0.8},
    "wonder": {"chords": [("D", "maj"), ("B", "min"), ("G", "maj"), ("A", "maj")], "bpm": 76, "bright": 0.55},
}


def hz(name: str, octave: int) -> float:
    return 440.0 * 2 ** ((NOTE[name[0]] + (1 if "#" in name else 0) + 12 * (octave - 4) - 9) / 12)


def chord_notes(root: str, kind: str, octave=3):
    r = hz(root, octave)
    third = 3 if kind == "min" else 4
    return [r, r * 2 ** (third / 12), r * 2 ** (7 / 12), r * 2]


def env_adsr(n, a=0.02, d=0.2, s=0.6, r=0.3, sr=SR):
    t = np.arange(n) / sr
    dur = n / sr
    e = np.where(t < a, t / a, np.where(t < a + d, 1 - (1 - s) * (t - a) / d, s))
    rel = np.clip((dur - t) / r, 0, 1)
    return e * rel


def music(seconds: float, mood: str, seed: int = 1) -> np.ndarray:
    m = MOODS[mood]
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    out = np.zeros(n, np.float32)
    beat = 60 / m["bpm"]
    bar = beat * 4
    k = 0
    t0 = 0.0
    while t0 < seconds:
        root, kind = m["chords"][k % len(m["chords"])]
        notes = chord_notes(root, kind)
        a, b = int(t0 * SR), min(n, int((t0 + bar) * SR))
        tt = np.arange(b - a) / SR
        pad = sum(np.sin(2 * np.pi * f * tt) * 0.5 + 0.18 * np.sin(4 * np.pi * f * tt) for f in notes[:3]) / 3
        out[a:b] += 0.16 * pad * env_adsr(b - a, 0.4, 0.4, 0.8, 0.5)
        for j in range(8):                                     # plucked arpeggio, eighth notes
            s = int((t0 + j * beat / 2) * SR)
            if s >= n:
                break
            f = notes[(j * 2 + rng.integers(0, 2)) % 4] * 2
            ln = min(n - s, int(beat * SR))
            tp = np.arange(ln) / SR
            pl = np.sin(2 * np.pi * f * tp) * np.exp(-tp * (5 - 2 * m["bright"])) + 0.25 * np.sin(4 * np.pi * f * tp) * np.exp(-tp * 9)
            out[s:s + ln] += 0.09 * pl
        bass = int(t0 * SR)
        ln = min(n - bass, int(bar * SR))
        tb = np.arange(ln) / SR
        out[bass:bass + ln] += 0.12 * np.sin(2 * np.pi * notes[0] / 2 * tb) * env_adsr(ln, 0.02, 0.5, 0.5, 0.4)
        t0 += bar
        k += 1
    fade = min(n, int(1.5 * SR))
    out[:fade] *= np.linspace(0, 1, fade)
    out[-fade:] *= np.linspace(1, 0, fade)
    return out


def lowpass(x, cutoff):
    k = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - k) * x[i] + k * acc
        y[i] = acc
    return y


def ambience(seconds: float, kind: str, seed: int = 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    # cheap low-pass by moving average (fast) for wind / city hum
    win = 64 if kind != "room" else 400
    bed = np.convolve(noise, np.ones(win) / win, mode="same") * (0.25 if kind != "room" else 0.15)
    slow = 0.6 + 0.4 * np.sin(2 * np.pi * np.arange(n) / SR * 0.13)
    bed *= slow
    if kind in ("park", "park_sunset"):
        t = 0.6
        while t < seconds - 1:                                # birdsong: short chirp sweeps
            s = int(t * SR)
            f0 = rng.uniform(2600, 4200)
            for c in range(rng.integers(2, 5)):
                ln = int(0.07 * SR)
                st = s + c * int(0.11 * SR)
                if st + ln >= n:
                    break
                tt = np.arange(ln) / SR
                f = f0 + 1800 * tt / 0.07 * (1 if c % 2 else -0.6)
                bed[st:st + ln] += 0.035 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.hanning(ln)
            t += rng.uniform(1.5, 3.5)
    if kind == "street":
        tt = np.arange(n) / SR
        bed += 0.02 * np.sin(2 * np.pi * 55 * tt) * slow
    return bed.astype(np.float32)


def footstep(rng, surface="grass", weight=1.0) -> np.ndarray:
    ln = int(0.12 * SR)
    t = np.arange(ln) / SR
    noise = rng.standard_normal(ln)
    body = np.convolve(noise, np.ones(18 if surface == "grass" else 6) / (18 if surface == "grass" else 6), mode="same")
    thud = np.sin(2 * np.pi * (90 if surface != "grass" else 70) * t) * np.exp(-t * 40)
    return ((0.5 * body * np.exp(-t * 30) + 0.6 * thud) * 0.35 * weight).astype(np.float32)


def read_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        sr = w.getframerate()
    if w.getnchannels() == 2:
        x = x.reshape(-1, 2).mean(axis=1)
    if sr != SR:
        x = np.interp(np.arange(int(len(x) * SR / sr)) * sr / SR, np.arange(len(x)), x).astype(np.float32)
    return x


def mix_scene(seconds: float, fps: int, cues: list[dict], mood: str, ambience_kind: str, surface: str, seed: int = 1,
              character_weight: dict | None = None) -> tuple[np.ndarray, dict]:
    n = int(seconds * SR)
    dialog = np.zeros(n, np.float32)
    foley = np.zeros(n, np.float32)
    rng = np.random.default_rng(seed)
    placed = {"dialogue": 0, "footsteps": 0}
    for c in cues:
        s = int((c["frame"] - 1) / fps * SR)
        if s >= n:
            continue
        if c["type"] == "dialogue":
            x = read_mono(Path(c["wav"]))
            e = min(n, s + len(x))
            dialog[s:e] += x[: e - s]
            placed["dialogue"] += 1
        elif c["type"] == "footstep":
            w = (character_weight or {}).get(c["char"], 1.0)
            x = footstep(rng, surface, w)
            e = min(n, s + len(x))
            foley[s:e] += x[: e - s]
            placed["footsteps"] += 1
    mus = music(seconds, mood, seed)
    amb = ambience(seconds, ambience_kind, seed)
    # duck music + ambience under dialogue (smoothed envelope, ~10 dB)
    env = np.abs(dialog)
    k = int(0.25 * SR)
    env = np.convolve(env, np.ones(k) / k, mode="same")
    duck = 1.0 - 0.68 * np.clip(env / (env.max() + 1e-9) * 3, 0, 1)
    left = dialog * 1.0 + foley * 0.9 + mus * duck * 0.55 + amb * duck * 0.5
    right = dialog * 1.0 + foley * 0.9 + mus * duck * 0.55 + np.roll(amb, 2400) * duck * 0.5
    st = np.stack([left, right], axis=1)
    peak = float(np.abs(st).max()) or 1.0
    st = st / peak * 0.9
    return st.astype(np.float32), placed


def write_stereo(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def read_stereo(path: Path, seconds: float | None = None) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        ch = w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    st = x.reshape(-1, ch) if ch == 2 else np.stack([x, x], axis=1)
    if seconds is not None:
        n = int(round(seconds * SR))
        st = st[:n] if len(st) >= n else np.concatenate([st, np.zeros((n - len(st), 2), np.float32)])
    return st
