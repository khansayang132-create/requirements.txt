"""Voice analysis. Every number here is measured from the recording with signal processing
(WORLD F0 tracking, spectral envelope, energy envelope). Accent and pronunciation cannot be
measured without a speech recogniser, so they are recorded as *declared* by the user and the
report says so instead of inventing a value."""
from __future__ import annotations

import warnings

import numpy as np

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import pyworld as pw

ANALYSIS_SR = 16000
FRAME_MS = 5.0


def _frames_rms(x: np.ndarray, sr: int, win_ms: float = 25, hop_ms: float = 10) -> np.ndarray:
    win, hop = int(sr * win_ms / 1000), int(sr * hop_ms / 1000)
    if x.size < win:
        return np.array([np.sqrt(np.mean(x**2)) if x.size else 0.0])
    idx = np.arange(0, x.size - win + 1, hop)
    frames = np.stack([x[i:i + win] for i in idx])
    return np.sqrt(np.mean(frames**2, axis=1) + 1e-12)


def world_features(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.ascontiguousarray(x, dtype=np.float64)
    f0, t = pw.dio(x, sr, f0_floor=60.0, f0_ceil=600.0, frame_period=FRAME_MS)
    f0 = pw.stonemask(x, f0, t, sr)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap = pw.d4c(x, f0, t, sr)
    return f0, sp, ap


def formants(x: np.ndarray, sr: int, order: int = 12) -> np.ndarray:
    """Median F1-F3 (Hz) from LPC roots on voiced, non-quiet frames. Insensitive to spectral tilt,
    so a studio recording and a synthetic voice are measured on the same scale."""
    from scipy.linalg import solve_toeplitz

    from .audio import resample
    if sr != 10000:
        x, sr = resample(x, sr, 10000), 10000
    x = np.append(x[0], x[1:] - 0.63 * x[:-1])
    win, hop = int(0.03 * sr), int(0.01 * sr)
    level = np.sqrt(np.mean(x ** 2)) + 1e-12
    window = np.hamming(win)
    found = []
    for i in range(0, x.size - win, hop):
        frame = x[i:i + win] * window
        if np.sqrt(np.mean(frame ** 2)) < 0.3 * level:
            continue
        r = np.correlate(frame, frame, "full")[win - 1:win + order]
        if r[0] <= 0:
            continue
        try:
            a = solve_toeplitz(r[:order], -r[1:order + 1])
        except np.linalg.LinAlgError:
            continue
        roots = np.roots(np.concatenate([[1.0], a]))
        roots = roots[np.imag(roots) > 0]
        f = np.angle(roots) * sr / (2 * np.pi)
        bw = -np.log(np.abs(roots)) * sr / np.pi
        f = np.sort(f[(f > 200) & (f < 4500) & (bw < 400)])
        if f.size >= 3:
            found.append(f[:3])
    return np.median(np.array(found), axis=0) if found else np.array([500.0, 1500.0, 2500.0])


def formant_scale(x: np.ndarray, sr: int) -> float:
    """Geometric mean of F1-F3. A longer vocal tract (deeper voice) gives a lower value; the
    ratio between two voices drives the formant warp in clone.py."""
    return float(np.exp(np.log(formants(x, sr)).mean()))


def _label(value: float, cuts: list[tuple[float, str]], last: str) -> str:
    for limit, name in cuts:
        if value < limit:
            return name
    return last


def analyze_voice(x: np.ndarray, sr: int, declared_language: str = "", declared_accent: str = "") -> dict:
    from .audio import resample

    if sr != ANALYSIS_SR:
        x = resample(x, sr, ANALYSIS_SR)
        sr = ANALYSIS_SR
    duration = x.size / sr
    if duration < 3.0:
        raise ValueError("recording is too short: at least 3 seconds of speech is needed")
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak < 1e-3:
        raise ValueError("recording is silent")
    x = x / peak * 0.9

    f0, sp, ap = world_features(x, sr)
    voiced = f0[f0 > 0]
    if voiced.size < 40:
        raise ValueError("no clear voiced speech found in the recording")
    log_f0 = np.log(voiced)
    semis = 12 * np.log2(voiced / np.median(voiced))
    f0_range_st = float(np.percentile(semis, 95) - np.percentile(semis, 5))

    # Jitter: relative frame-to-frame period change inside voiced runs.
    periods = 1.0 / voiced
    jitter = float(np.mean(np.abs(np.diff(periods))) / np.mean(periods) * 100) if periods.size > 2 else 0.0

    # Harmonics-to-noise from WORLD aperiodicity (0 = fully periodic) in the 0-4 kHz band.
    band = int(ap.shape[1] * 4000 / (sr / 2))
    ap_voiced = ap[f0 > 0][:, :band]
    hnr_db = float(np.clip(10 * np.log10((1 - ap_voiced.mean() + 1e-6) / (ap_voiced.mean() + 1e-6)), -10, 40))

    # Spectral shape.
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
    freqs = np.fft.rfftfreq(x.size, 1 / sr)
    centroid = float((freqs * spec).sum() / spec.sum())
    lo = spec[(freqs > 80) & (freqs < 1000)].sum()
    hi = spec[(freqs > 1000) & (freqs < 8000)].sum()
    tilt_db = float(10 * np.log10(hi / lo + 1e-12))
    fmts = formants(x, sr)
    fscale = float(np.exp(np.log(fmts).mean()))

    # Energy envelope -> pauses, breaths, speaking rate.
    rms = _frames_rms(x, sr)
    db = 20 * np.log10(rms + 1e-9)
    floor = np.percentile(db, 10)
    speech_level = np.percentile(db, 90)
    thresh = floor + 0.35 * (speech_level - floor)
    active = db > thresh
    hop = 0.01
    pauses, breaths, run = [], 0, 0
    frame_len = int(0.025 * sr)
    for i, a in enumerate(np.append(active, True)):
        if not a:
            run += 1
            continue
        if run * hop >= 0.15 and i - run > 0:  # internal pause (not leading silence)
            pauses.append(run * hop)
            seg = x[int((i - run) * hop * sr): int(i * hop * sr)]
            if seg.size > frame_len:
                seg_spec = np.abs(np.fft.rfft(seg)) + 1e-12
                flatness = np.exp(np.mean(np.log(seg_spec))) / np.mean(seg_spec)
                seg_db = 20 * np.log10(np.sqrt(np.mean(seg**2)) + 1e-9)
                if flatness > 0.25 and seg_db > floor + 6:
                    breaths += 1  # noisy, broadband, above the floor: an audible breath
        run = 0
    speech_time = float(active.sum() * hop)

    # Syllable nuclei: peaks of the smoothed energy envelope inside active speech.
    from scipy.signal import find_peaks
    smooth = np.convolve(db, np.ones(5) / 5, mode="same")
    peaks, _ = find_peaks(np.where(active, smooth, floor), prominence=3, distance=8)
    syll_rate = float(len(peaks) / speech_time) if speech_time > 0 else 0.0
    wpm = syll_rate * 60 / 1.5  # ~1.5 syllables per word in English/Indonesian conversation

    energy_var = float(np.std(db[active])) if active.any() else 0.0
    f0_median = float(np.median(voiced))
    expressiveness = "monotone" if f0_range_st < 4 else "neutral" if f0_range_st < 9 else "expressive"

    return {
        "duration_s": round(duration, 2),
        "pitch": {
            "f0_median_hz": round(f0_median, 1),
            "f0_mean_log": round(float(log_f0.mean()), 4),
            "f0_std_log": round(float(log_f0.std()), 4),
            "f0_p5_hz": round(float(np.percentile(voiced, 5)), 1),
            "f0_p95_hz": round(float(np.percentile(voiced, 95)), 1),
            "range_semitones": round(f0_range_st, 2),
            "register": _label(f0_median, [(110, "low"), (165, "mid-low"), (220, "mid-high")], "high"),
        },
        "depth": {
            "formant_scale_hz": round(fscale, 1),
            "formants_hz": [round(float(f)) for f in fmts],
            "label": _label(fscale, [(1230, "deep"), (1380, "balanced")], "light"),
        },
        "texture": {
            "hnr_db": round(hnr_db, 2),
            "jitter_percent": round(jitter, 3),
            "label": _label(hnr_db, [(8, "breathy/rough"), (15, "soft")], "clear"),
        },
        "tone": {
            "spectral_centroid_hz": round(centroid, 1),
            "spectral_tilt_db": round(tilt_db, 2),
            "label": _label(tilt_db, [(-22, "warm/dark"), (-12, "neutral")], "bright"),
        },
        "speed": {
            "syllables_per_s": round(syll_rate, 2),
            "estimated_wpm": round(wpm),
            "label": _label(wpm, [(120, "slow"), (165, "moderate")], "fast"),
        },
        "energy": {
            "speech_level_db": round(float(speech_level), 2),
            "dynamic_range_db": round(float(speech_level - floor), 2),
            "variation_db": round(energy_var, 2),
        },
        "rhythm": {
            "speech_ratio": round(speech_time / duration, 3),
            "pause_count": len(pauses),
            "mean_pause_s": round(float(np.mean(pauses)), 3) if pauses else 0.0,
            "pauses_per_min": round(len(pauses) / duration * 60, 2),
            "breath_count": breaths,
        },
        "emotion": {"expressiveness": expressiveness, "pitch_range_semitones": round(f0_range_st, 2)},
        "accent": {"value": declared_accent or "not declared", "source": "declared by user (not measured)"},
        "pronunciation": {"language": declared_language or "not declared",
                          "source": "declared by user (needs a speech recogniser to measure)"},
    }
