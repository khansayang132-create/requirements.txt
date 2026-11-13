"""Audio intelligence: objective measurements and defect detection for generated speech.

Everything here is a number computed from the samples. Subjective listening (naturalness, acting) is a separate,
human field and is reported as NOT TESTED by machines.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

FRAME = 0.02                     # 20 ms analysis frames

DEFAULT_LIMITS = {
    "sample_rate": 48000, "channels": 1, "min_rms_dbfs": -35.0, "max_peak_dbfs": -0.3, "max_clip_ratio": 0.0005,
    "max_internal_silence_s": 1.2, "max_edge_silence_s": 0.35, "min_speech_ratio": 0.45, "max_dc": 0.02,
    "max_noise_floor_dbfs": -50.0, "cutoff_db_above_floor": 30.0, "duration_tolerance": 0.45,
}


def read_wav(path: Path) -> tuple[np.ndarray, int, int]:
    with wave.open(str(path), "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"expected 16-bit PCM, got {sw * 8}-bit")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch)
    return x, sr, ch


def db(v: float) -> float:
    return float(20 * np.log10(max(v, 1e-9)))


def expected_seconds(text: str, wpm: float) -> float:
    words = max(1, len(text.split()))
    pauses = text.count(",") * 0.2 + sum(text.count(c) for c in ".!?") * 0.35
    return words / max(60.0, wpm) * 60 + pauses


def measure(path: Path, text: str | None = None, wpm: float = 150, limits: dict | None = None) -> dict:
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    x, sr, ch = read_wav(path)
    mono = x.mean(axis=1) if x.ndim == 2 else x
    n = len(mono)
    dur = n / sr
    hop = max(1, int(sr * FRAME))
    frames = mono[: n // hop * hop].reshape(-1, hop) if n >= hop else mono.reshape(1, -1)
    frms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    peak = float(np.abs(mono).max()) if n else 0.0
    rms = float(np.sqrt((mono ** 2).mean())) if n else 0.0
    voiced_thr = 10 ** (-40 / 20)                     # speech frames are louder than -40 dBFS
    voiced = frms > voiced_thr
    quiet = frms[~voiced]
    overall = float(np.percentile(frms, 10)) if len(frms) else 1e-9
    # noise floor: the quietest non-speech frames; if noise fills every pause there are none, so the overall low percentile
    floor = min(overall, float(np.percentile(quiet, 10))) if len(quiet) >= 5 else overall
    idx = np.nonzero(voiced)[0]
    lead = float(idx[0] * FRAME) if len(idx) else dur
    trail = float((len(frms) - 1 - idx[-1]) * FRAME) if len(idx) else dur
    longest, run = 0, 0
    if len(idx):
        for v in voiced[idx[0]: idx[-1] + 1]:
            run = 0 if v else run + 1
            longest = max(longest, run)
    tail = frms[-3:] if len(frms) >= 3 else frms
    clip = float((np.abs(mono) >= 0.999).mean()) if n else 0.0
    m = {
        "duration_s": round(dur, 3), "sample_rate": sr, "channels": ch, "rms_dbfs": round(db(rms), 2), "peak_dbfs": round(db(peak), 2),
        "clip_ratio": round(clip, 6), "dc_offset": round(float(mono.mean()) if n else 0.0, 5), "noise_floor_dbfs": round(db(floor), 2),
        "speech_ratio": round(float(voiced.mean()) if len(voiced) else 0.0, 3), "leading_silence_s": round(lead, 3),
        "trailing_silence_s": round(trail, 3), "longest_internal_silence_s": round(longest * FRAME, 3),
        "tail_level_db_above_floor": round(db(float(tail.mean())) - db(floor), 2) if len(tail) else 0.0,
    }
    if text:
        exp = expected_seconds(text, wpm)
        m["expected_duration_s"] = round(exp, 2)
        m["duration_ratio"] = round((dur - lead - trail) / exp, 3) if exp else None
    m["defects"] = defects(m, lim)
    m["score"] = score(m)
    return m


def defects(m: dict, lim: dict) -> list[dict]:
    d = []

    def add(code, detail, fix):
        d.append({"code": code, "detail": detail, "fix": fix})

    if m["speech_ratio"] == 0 or m["rms_dbfs"] < -60:
        add("silence", f"no speech detected (rms {m['rms_dbfs']} dBFS)", "regenerate")
    elif m["rms_dbfs"] < lim["min_rms_dbfs"]:
        add("too_quiet", f"rms {m['rms_dbfs']} dBFS < {lim['min_rms_dbfs']}", "gain")
    if m["clip_ratio"] > lim["max_clip_ratio"] or m["peak_dbfs"] > lim["max_peak_dbfs"]:
        add("clipping", f"peak {m['peak_dbfs']} dBFS, clipped {m['clip_ratio']:.4%}", "gain")
    if m["sample_rate"] != lim["sample_rate"]:
        add("sample_rate", f"{m['sample_rate']} Hz, expected {lim['sample_rate']}", "resample")
    if m["channels"] != lim["channels"]:
        add("channels", f"{m['channels']} channels, expected {lim['channels']}", "downmix")
    if abs(m["dc_offset"]) > lim["max_dc"]:
        add("dc_offset", f"DC {m['dc_offset']}", "highpass")
    if m["noise_floor_dbfs"] > lim["max_noise_floor_dbfs"]:
        add("noise", f"noise floor {m['noise_floor_dbfs']} dBFS", "denoise")
    if m["longest_internal_silence_s"] > lim["max_internal_silence_s"]:
        add("internal_gap", f"{m['longest_internal_silence_s']} s gap inside the line", "regenerate")
    if m["leading_silence_s"] > lim["max_edge_silence_s"] or m["trailing_silence_s"] > lim["max_edge_silence_s"] + 0.2:
        add("edge_silence", f"lead {m['leading_silence_s']} s / trail {m['trailing_silence_s']} s", "trim")
    if m["trailing_silence_s"] < 0.02 and m["tail_level_db_above_floor"] > lim["cutoff_db_above_floor"]:
        add("abrupt_cutoff", f"speech still {m['tail_level_db_above_floor']} dB above the floor at the last frame", "regenerate")
    if m.get("duration_ratio") is not None:
        r = m["duration_ratio"]
        if r < 1 - lim["duration_tolerance"]:
            add("too_short", f"{r:.2f}x the expected length: words may be missing", "regenerate")
        elif r > 1 + lim["duration_tolerance"] * 1.5:
            add("too_long", f"{r:.2f}x the expected length", "regenerate")
    return d


WEIGHTS = {"silence": 100, "clipping": 25, "too_quiet": 10, "sample_rate": 15, "channels": 15, "dc_offset": 5, "noise": 10,
           "internal_gap": 20, "edge_silence": 5, "abrupt_cutoff": 30, "too_short": 35, "too_long": 15}


def score(m: dict) -> float:
    s = 100.0 - sum(WEIGHTS.get(d["code"], 10) for d in m["defects"])
    if m.get("duration_ratio") is not None:
        s -= min(15.0, abs(1 - m["duration_ratio"]) * 20)
    return round(max(0.0, s), 2)


def blocking(m: dict) -> list[str]:
    """Defects that make a take unusable (others can be processed away)."""
    return [d["code"] for d in m["defects"] if d["code"] in ("silence", "abrupt_cutoff", "too_short", "internal_gap", "too_long")]


def f0_median(path: Path, fmin: float = 70, fmax: float = 500) -> float | None:
    """Median fundamental frequency (Hz) over voiced 40 ms frames, by normalised autocorrelation."""
    x, sr, _ = read_wav(path)
    x = x.mean(axis=1) if x.ndim == 2 else x
    win, hop = int(0.04 * sr), int(0.01 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    f0s = []
    for i in range(0, len(x) - win, hop):
        fr = x[i:i + win] - x[i:i + win].mean()
        if np.sqrt((fr ** 2).mean()) < 10 ** (-35 / 20):
            continue
        ac = np.correlate(fr, fr, "full")[win - 1:]
        ac /= ac[0] + 1e-12
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.5:
            f0s.append(sr / lag)
    return round(float(np.median(f0s)), 1) if len(f0s) >= 5 else None
