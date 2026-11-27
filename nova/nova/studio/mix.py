"""Audio production extras: voice polish (high-pass, gentle compression, de-essing only when
sibilance is high), background music with ducking under the voice, and sound effects.

Music and effects are only ever the user's own or licensed files; NOVA ships none."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .. import audio as A


def sibilance_ratio(x: np.ndarray, sr: int) -> float:
    S = np.abs(np.fft.rfft(x[: (x.size // 4096) * 4096].reshape(-1, 4096) * np.hanning(4096), axis=1)).sum(0)
    f = np.fft.rfftfreq(4096, 1 / sr)
    voice = S[(f > 100) & (f < 4000)].sum() + 1e-9
    return float(S[(f > 5000) & (f < 9000)].sum() / voice)


def polish(x: np.ndarray, sr: int) -> tuple[np.ndarray, dict]:
    sib = sibilance_ratio(x, sr) if x.size > 8192 else 0.0
    chain = ["highpass=f=70", "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=1"]
    if sib > 0.22:
        chain.append("deesser=i=0.25")
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "i.wav", Path(td) / "o.wav"
        sf.write(str(src), np.clip(x, -1, 1), sr, subtype="FLOAT")
        p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", ",".join(chain),
                            "-ar", str(sr), str(dst)], capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            raise A.AudioError(f"polish failed: {p.stderr[:200]}")
        y, _ = sf.read(str(dst), dtype="float64")
    y = A.to_mono(y)
    y = y[: x.size] if y.size >= x.size else np.pad(y, (0, x.size - y.size))
    return y, {"chain": chain, "sibilance_ratio": round(sib, 3), "deessed": sib > 0.22}


def duck_envelope(voice: np.ndarray, sr: int, duck_db: float, attack_ms=60, release_ms=400) -> np.ndarray:
    hop = max(1, int(sr * 0.01))
    rms = np.sqrt(np.convolve(voice ** 2, np.ones(hop) / hop, mode="same") + 1e-12)
    active = (20 * np.log10(rms) > -40).astype(float)
    a, r = np.exp(-1 / (sr * attack_ms / 1000)), np.exp(-1 / (sr * release_ms / 1000))
    env = np.empty_like(active)
    level = 0.0
    step = hop  # compute on a coarse grid, then interpolate (fast enough for minutes of audio)
    grid = active[::step]
    out = np.empty_like(grid)
    ga, gr = a ** step, r ** step
    for i, v in enumerate(grid):
        level = v + (level - v) * (ga if v > level else gr)
        out[i] = level
    env = np.interp(np.arange(active.size), np.arange(grid.size) * step, out)
    return 10 ** (duck_db * env / 20)


def mix(voice: np.ndarray, sr: int, music: str | None = None, music_db: float = -18.0, duck_db: float = -10.0,
        fade_s: float = 1.5, effects: list[dict] | None = None) -> tuple[np.ndarray, dict]:
    """voice: mastered narration. music: path to the user's file, looped to length. effects:
    [{path, at_s, gain_db}]."""
    out = voice.copy()
    report: dict = {"music": None, "effects": []}
    if music:
        m, _ = A.load_audio(music, sr=sr)
        if m.size == 0:
            raise A.AudioError("music file has no audio")
        reps = int(np.ceil(voice.size / m.size))
        m = np.tile(m, reps)[: voice.size]
        m = m / (np.max(np.abs(m)) + 1e-9) * 10 ** (music_db / 20)
        n = min(m.size // 2, int(fade_s * sr))
        if n:
            m[:n] *= np.linspace(0, 1, n)
            m[-n:] *= np.linspace(1, 0, n)
        env = duck_envelope(voice, sr, duck_db)
        out = out + m * env
        report["music"] = {"file": Path(music).name, "level_db": music_db, "duck_db": duck_db,
                           "ducked_share": round(float(np.mean(env < 10 ** (duck_db / 40))), 3)}
    for fx in effects or []:
        e, _ = A.load_audio(fx["path"], sr=sr)
        at = int(float(fx.get("at_s", 0)) * sr)
        if at >= out.size:
            continue
        e = e[: out.size - at] * 10 ** (float(fx.get("gain_db", -6)) / 20)
        out[at:at + e.size] += e
        report["effects"].append({"file": Path(fx["path"]).name, "at_s": fx.get("at_s", 0)})
    peak = np.max(np.abs(out))
    if peak > 0.99:
        out = out / peak * 0.99
        report["peak_scaled"] = True
    return out, report
