"""Mastering: ITU-R BS.1770-4 loudness (K-weighting + gating), gentle noise reduction only
when a noise floor is measurable, silence management, fades, 4x-oversampled true-peak limiting
and sample-rate normalisation. Gain changes are smooth and limited, so voice character is kept."""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter, resample_poly

from .audio import resample


def _k_weighting(sr: int) -> list[tuple[np.ndarray, np.ndarray]]:
    # Shelf + high-pass from BS.1770, designed for any sample rate (same derivation as pyloudnorm).
    G, Q, fc = 3.999843853973347, 0.7071752369554196, 1681.974450955533
    K = np.tan(np.pi * fc / sr)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    b1 = np.array([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0])
    a1 = np.array([1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    Q2, fc2 = 0.5003270373238773, 38.13547087602444
    K2 = np.tan(np.pi * fc2 / sr)
    a0 = 1 + K2 / Q2 + K2 * K2
    b2 = np.array([1, -2, 1])
    a2 = np.array([1, 2 * (K2 * K2 - 1) / a0, (1 - K2 / Q2 + K2 * K2) / a0])
    return [(b1, a1), (b2, a2)]


def integrated_loudness(x: np.ndarray, sr: int) -> float:
    if x.size < int(0.4 * sr):
        return -70.0
    y = x
    for b, a in _k_weighting(sr):
        y = lfilter(b, a, y)
    block, hop = int(0.4 * sr), int(0.1 * sr)
    n = 1 + (y.size - block) // hop
    z = np.array([np.mean(y[i * hop:i * hop + block] ** 2) for i in range(n)])
    lk = -0.691 + 10 * np.log10(z + 1e-12)
    z = z[lk > -70]
    if z.size == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(z.mean()) - 10
    z = z[(-0.691 + 10 * np.log10(z + 1e-12)) > rel]
    return float(-0.691 + 10 * np.log10(z.mean() + 1e-12)) if z.size else -70.0


def true_peak_db(x: np.ndarray) -> float:
    up = resample_poly(x, 4, 1)
    return float(20 * np.log10(np.max(np.abs(up)) + 1e-12))


def limit(x: np.ndarray, sr: int, ceiling_db: float = -1.0, release_ms: float = 60.0) -> np.ndarray:
    ceiling = 10 ** (ceiling_db / 20)
    peak = np.abs(resample_poly(x, 4, 1)).reshape(-1, 4).max(axis=1)[: x.size] if x.size else x
    if peak.size < x.size:
        peak = np.pad(peak, (0, x.size - peak.size))
    need = np.minimum(1.0, ceiling / (peak + 1e-12))
    # Look-ahead 2 ms: the gain starts falling before the peak arrives.
    la = max(1, int(0.002 * sr))
    need = np.minimum.reduce([np.roll(need, -k) for k in range(la)])
    rel = np.exp(-1.0 / (release_ms / 1000 * sr))
    gain = np.empty_like(need)
    g = 1.0
    for i, t in enumerate(need):
        g = t if t < g else t + (g - t) * rel
        gain[i] = g
    return x * gain


def reduce_noise(x: np.ndarray, sr: int, max_reduction_db: float = 8.0) -> tuple[np.ndarray, dict]:
    n_fft, hop = 1024, 256
    if x.size < n_fft * 4:
        return x, {"applied": False, "reason": "too short"}
    win = np.hanning(n_fft)
    frames = np.stack([x[i:i + n_fft] * win for i in range(0, x.size - n_fft, hop)])
    spec = np.fft.rfft(frames, axis=1)
    mag = np.abs(spec)
    energy = mag.mean(axis=1)
    quiet = energy <= np.percentile(energy, 10)
    noise = mag[quiet].mean(axis=0)
    scale = np.sqrt(np.sum(win ** 2) * n_fft / 2)  # per-bin magnitude -> time-domain RMS
    noise_db = float(20 * np.log10(np.sqrt(np.sum(noise ** 2)) / scale + 1e-12))
    speech_db = float(20 * np.log10(np.sqrt(np.sum(mag[~quiet].mean(axis=0) ** 2)) / scale + 1e-12))
    if noise_db < -50 or speech_db - noise_db > 40:  # nothing audible to remove (studio TTS sits near -60)
        return x, {"applied": False, "reason": "no measurable noise floor", "snr_db": round(speech_db - noise_db, 1)}
    floor = 10 ** (-max_reduction_db / 20)
    gain = np.maximum(floor, 1 - 1.5 * noise / (mag + 1e-12))
    gain = np.apply_along_axis(lambda g: np.convolve(g, np.ones(3) / 3, mode="same"), 0, gain)
    out_frames = np.fft.irfft(spec * gain, n=n_fft, axis=1) * win
    y = np.zeros(x.size)
    norm = np.zeros(x.size)
    for k, i in enumerate(range(0, x.size - n_fft, hop)):
        y[i:i + n_fft] += out_frames[k]
        norm[i:i + n_fft] += win ** 2
    y = np.where(norm > 1e-3, y / np.maximum(norm, 1e-3), x)
    return y, {"applied": True, "max_reduction_db": max_reduction_db, "noise_floor_db": round(noise_db, 1),
               "snr_db": round(speech_db - noise_db, 1)}


def manage_silence(x: np.ndarray, sr: int, edge_s: float = 0.15, max_gap_s: float = 1.6,
                   threshold_db: float = -50.0) -> np.ndarray:
    hop = int(0.01 * sr)
    if x.size < hop * 3:
        return x
    rms = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, mode="same") + 1e-12)
    active = 20 * np.log10(rms) > threshold_db
    idx = np.flatnonzero(active)
    if idx.size == 0:
        return x
    start = max(0, idx[0] - int(edge_s * sr))
    end = min(x.size, idx[-1] + int(edge_s * sr))
    x, active = x[start:end], active[start:end]
    # Shorten any internal silence longer than max_gap_s (directed pauses are shorter than this).
    out, i, max_gap = [], 0, int(max_gap_s * sr)
    while i < x.size:
        if not active[i]:
            j = i
            while j < x.size and not active[j]:
                j += 1
            seg = x[i:j]
            out.append(seg if seg.size <= max_gap else np.concatenate([seg[: max_gap // 2], seg[-max_gap // 2:]]))
            i = j
        else:
            j = i
            while j < x.size and active[j]:
                j += 1
            out.append(x[i:j])
            i = j
    return np.concatenate(out)


def fade(x: np.ndarray, sr: int, fade_in_ms: float = 15, fade_out_ms: float = 60) -> np.ndarray:
    x = x.copy()
    a, b = min(x.size, int(sr * fade_in_ms / 1000)), min(x.size, int(sr * fade_out_ms / 1000))
    if a:
        x[:a] *= np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    if b:
        x[-b:] *= np.cos(np.linspace(0, np.pi / 2, b)) ** 2
    return x


def master(x: np.ndarray, sr: int, target_sr: int = 48000, target_lufs: float = -16.0,
           ceiling_db: float = -1.0, noise_reduction: bool = True) -> tuple[np.ndarray, int, dict]:
    report: dict = {"input_lufs": round(integrated_loudness(x, sr), 2)}
    x = x - np.mean(x)  # DC offset
    if noise_reduction:
        x, report["noise_reduction"] = reduce_noise(x, sr)
    x = manage_silence(x, sr)
    if sr != target_sr:
        x = resample(x, sr, target_sr)
        sr = target_sr
    # Leveling: two passes of normalise + limit so the limiter's gain loss is made up.
    for _ in range(2):
        gain_db = float(np.clip(target_lufs - integrated_loudness(x, sr), -30, 30))
        x = limit(x * 10 ** (gain_db / 20), sr, ceiling_db)
    x = fade(x, sr)
    report.update({
        "output_lufs": round(integrated_loudness(x, sr), 2),
        "true_peak_dbtp": round(true_peak_db(x), 2),
        "target_lufs": target_lufs, "ceiling_dbtp": ceiling_db,
        "sample_rate": sr, "duration_s": round(x.size / sr, 2),
    })
    return x, sr, report
