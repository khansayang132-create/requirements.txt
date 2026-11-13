"""Cinematic audio factory: generated stems (music, ambience, cartoon effects), the mix, and FFmpeg mastering.

All non-dialogue sound is synthesised here (no third-party samples, so the licence is clean). Each stem is written
separately; the master chain is high-pass, presence EQ, gentle compression, then two-pass EBU R128 loudness.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from . import analysis
from .engines.base import SR, write_wav

NOTES = {"C": 261.63, "D": 293.66, "E": 329.63, "F": 349.23, "G": 392.0, "A": 440.0, "B": 493.88}
PROG = {"warm": ["C", "A", "F", "G"], "tense": ["A", "F", "D", "E"], "joyful": ["F", "G", "E", "A"]}


def moving_average(x: np.ndarray, k: int) -> np.ndarray:
    """Centred moving average in O(n) (cumulative sum), same result as convolving with a box of length k."""
    c = np.cumsum(np.concatenate([np.zeros(k // 2 + 1), x, np.zeros(k - k // 2)]))
    return ((c[k:] - c[:-k]) / k)[: len(x)].astype(np.float32)


def music(seconds: float, mood: str = "warm", seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    out = np.zeros(n, np.float32)
    bar = 60 / 88 * 4
    t0, k = 0.0, 0
    while t0 < seconds:
        root = NOTES[PROG.get(mood, PROG["warm"])[k % 4]] / 2
        a, b = int(t0 * SR), min(n, int((t0 + bar) * SR))
        tt = np.arange(b - a) / SR
        env = np.minimum(1, tt / 0.4) * np.minimum(1, (bar - tt) / 0.5)
        for mult in (1, 1.26 if mood != "tense" else 1.19, 1.5):
            out[a:b] += 0.05 * np.sin(2 * np.pi * root * mult * tt) * env
        for j in range(8):
            s = int((t0 + j * bar / 8) * SR)
            if s >= n:
                break
            ln = min(n - s, int(0.35 * SR))
            tp = np.arange(ln) / SR
            f = root * 2 * (1, 1.26, 1.5, 2)[(j + rng.integers(0, 2)) % 4]
            out[s:s + ln] += 0.035 * np.sin(2 * np.pi * f * tp) * np.exp(-tp * 7)
        t0 += bar
        k += 1
    return out


def ambience(seconds: float, kind: str = "room", seed: int = 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    w = 300 if kind == "room" else 60
    bed = np.convolve(rng.standard_normal(n), np.ones(w) / w, mode="same").astype(np.float32) * (0.08 if kind == "room" else 0.15)
    return bed


def sfx(kind: str, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if kind == "whoosh":
        n = int(0.6 * SR)
        t = np.arange(n) / SR
        noise = np.convolve(rng.standard_normal(n), np.ones(20) / 20, mode="same")
        return (noise * np.sin(np.pi * t / 0.6) ** 2 * 0.4).astype(np.float32)
    if kind == "boing":
        n = int(0.5 * SR)
        t = np.arange(n) / SR
        f = 220 + 180 * np.sin(2 * np.pi * 9 * t) * np.exp(-t * 4)
        return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 5) * 0.4).astype(np.float32)
    if kind == "pop":
        n = int(0.12 * SR)
        t = np.arange(n) / SR
        return (np.sin(2 * np.pi * (900 - 4000 * t) * t) * np.exp(-t * 40) * 0.5).astype(np.float32)
    raise ValueError(kind)


def loudnorm(src: Path, dst: Path, i=-16.0, tp=-1.5, lra=11.0, chain="highpass=f=70,equalizer=f=3000:t=q:w=1.2:g=2,acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120") -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", f"{chain},loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, check=False)
    m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S).group(0))
    af = (f"{chain},loudnorm=I={i}:TP={tp}:LRA={lra}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(dst)], check=True)
    r2 = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(dst), "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True, check=False)
    after = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r2.stderr, re.S).group(0))
    return {"before_lufs": float(m["input_i"]), "after_lufs": float(after["input_i"]), "after_true_peak": float(after["input_tp"])}


def master_production(studio, name: str, mood: str = "warm", amb: str = "room") -> dict:
    out = studio.home / "productions" / name
    meta = json.loads((out / "dialogue.json").read_text())
    dia, _sr, _ = analysis.read_wav(Path(meta["dialogue_wav"]))
    n = len(dia) + int(1.0 * SR)
    stems = {"dialogue": np.concatenate([np.zeros(int(0.5 * SR), np.float32), dia, np.zeros(n - len(dia) - int(0.5 * SR), np.float32)])[:n]}
    stems["music"] = music(n / SR, mood)
    stems["ambience"] = ambience(n / SR, amb)
    fx = np.zeros(n, np.float32)
    events = []
    for k, r in enumerate(meta["lines"]):                      # a soft transition swish between scenes, a pop on surprise lines
        if k and r.get("scene_id") != meta["lines"][k - 1].get("scene_id"):
            s = int((r["start_s"] + 0.5 - 0.4) * SR)
            w = sfx("whoosh", k)
            fx[s:s + len(w)] += w[: max(0, n - s)]
            events.append({"t": round(s / SR, 2), "sfx": "whoosh"})
        if r.get("emotion") == "surprised":
            s = int((r["start_s"] + 0.5 - 0.1) * SR)
            w = sfx("pop", k)
            fx[s:s + len(w)] += w[: max(0, n - s)]
            events.append({"t": round(s / SR, 2), "sfx": "pop"})
    stems["sfx"] = fx
    sd = out / "stems"
    for k, v in stems.items():
        write_wav(sd / f"{k}.wav", v)
    env = moving_average(np.abs(stems["dialogue"]), int(0.25 * SR))
    duck = 1 - 0.7 * np.clip(env / (env.max() + 1e-9) * 3, 0, 1)
    # stereo placement: each speaker at its own pan position
    left = stems["music"] * duck * 0.6 + stems["ambience"] * 0.5 + stems["sfx"] * 0.8
    right = stems["music"] * duck * 0.6 + np.roll(stems["ambience"], 2400) * 0.5 + stems["sfx"] * 0.8
    speakers = meta["speakers"]
    pans = {c: (-0.35 + 0.7 * i / max(1, len(speakers) - 1)) if len(speakers) > 1 else 0.0 for i, c in enumerate(speakers)}
    for r in meta["lines"]:
        x, _sr, _ = analysis.read_wav(Path(r["wav"]))
        s = int((r["start_s"] + 0.5) * SR)
        p = pans[r["character_id"]]
        seg = x[: max(0, n - s)]
        left[s:s + len(seg)] += seg * np.sqrt((1 - p) / 2) * 1.2
        right[s:s + len(seg)] += seg * np.sqrt((1 + p) / 2) * 1.2
    mix = np.stack([left, right], axis=1)
    mix = mix / (np.abs(mix).max() + 1e-9) * 0.8
    raw = write_wav(out / "mix_premaster.wav", mix)
    loud = loudnorm(raw, out / "master.wav")
    mp3 = out / "master.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out / "master.wav"), "-c:a", "libmp3lame", "-q:a", "2", str(mp3)], check=True)
    rep = {"master_wav": str(out / "master.wav"), "master_mp3": str(mp3), "stems": sorted(str(p) for p in sd.glob("*.wav")), "loudness": loud,
           "pans": pans, "sfx_events": events}
    (out / "master_report.json").write_text(json.dumps(rep, indent=2))
    return rep
