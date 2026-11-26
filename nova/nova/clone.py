"""Profile-matched voice conversion (WORLD vocoder, signal processing — not a neural model).

The base engine's speech is decomposed into F0, spectral envelope and aperiodicity. Then:
  * F0 is mapped in the log domain onto the profile's measured mean and spread, then shifted by
    the director's pitch offset and scaled by its intonation-range factor, so the direction
    survives the conversion;
  * the spectral envelope is warped along frequency by the ratio of the two voices' formant
    scales (vocal-tract length), clamped so it can never become cartoonish;
  * aperiodicity is kept, which preserves the timing and consonants of the base speech.

It reproduces the profile's pitch, register, intonation spread and vocal-tract depth. It does
not reproduce timbre details the way a trained neural cloning model does; that model plugs in
as an engine (see README "Neural cloning engines")."""
from __future__ import annotations

import warnings

import numpy as np

from .analysis import FRAME_MS, formant_scale, world_features

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import pyworld as pw

WORK_SR = 24000
MAX_WARP = (0.82, 1.22)


def _warp_envelope(sp: np.ndarray, alpha: float) -> np.ndarray:
    """alpha > 1 moves formants up (shorter tract), < 1 moves them down."""
    if abs(alpha - 1.0) < 1e-3:
        return sp
    bins = np.arange(sp.shape[1], dtype=np.float64)
    src = np.clip(bins / alpha, 0, sp.shape[1] - 1)
    out = np.empty_like(sp)
    for i in range(sp.shape[0]):
        out[i] = np.exp(np.interp(src, bins, np.log(sp[i] + 1e-16)))
    return out


def convert(x: np.ndarray, sr: int, profile_voice: dict, pitch_semitones: float = 0.0,
            pitch_range: float = 1.0, strength: float = 1.0,
            breathiness: float | None = None, source_scale: float | None = None) -> tuple[np.ndarray, int, dict]:
    from .audio import resample

    if x.size == 0:
        return x, sr, {}
    if sr != WORK_SR:
        x = resample(x, sr, WORK_SR)
        sr = WORK_SR
    peak = float(np.max(np.abs(x))) or 1.0
    f0, sp, ap = world_features(x / peak * 0.9, sr)
    voiced = f0 > 0
    report: dict = {"voiced_frames": int(voiced.sum())}
    if voiced.sum() < 5:
        return x, sr, report

    pitch = profile_voice["pitch"]
    mu_t, sd_t = pitch["f0_mean_log"], max(pitch["f0_std_log"], 0.02)
    lf0 = np.log(f0[voiced])
    mu_s, sd_s = lf0.mean(), max(lf0.std(), 0.02)
    target_mu = mu_t + np.log(2.0) * pitch_semitones / 12.0
    target_sd = sd_t * pitch_range
    mapped = (lf0 - mu_s) / sd_s * target_sd + target_mu
    lf0_new = (1 - strength) * lf0 + strength * mapped
    f0_new = f0.copy()
    f0_new[voiced] = np.clip(np.exp(lf0_new), 50.0, 800.0)

    # A fixed, calibrated source scale keeps the warp (and so the voice identity) identical for
    # every sentence; per-sentence estimates drift with the vowels each sentence happens to contain.
    src_scale = source_scale or formant_scale(x, sr)
    tgt_scale = profile_voice["depth"]["formant_scale_hz"]
    alpha = float(np.clip((tgt_scale / src_scale) ** strength, *MAX_WARP))
    sp_new = _warp_envelope(sp, alpha)
    breath = profile_voice.get("breathiness", 0.0) if breathiness is None else breathiness
    if breath > 0:  # soften: raise aperiodicity above ~1 kHz, more at high frequencies
        freqs = np.linspace(0, sr / 2, ap.shape[1])
        weight = np.clip((freqs - 1000) / 4000, 0, 1) * min(breath, 0.6)
        ap = ap + (1 - ap) * weight
        sp_new = sp_new * (1 - 0.5 * weight) ** 2  # and tilt the top end down

    y = pw.synthesize(f0_new, sp_new, ap, sr, frame_period=FRAME_MS)
    y = y[: x.size] if y.size > x.size else y
    y = y / (np.max(np.abs(y)) + 1e-9) * peak
    report.update({
        "source_f0_hz": round(float(np.exp(mu_s)), 1),
        "target_f0_hz": round(float(np.exp(target_mu)), 1),
        "output_f0_hz": round(float(np.exp(lf0_new.mean())), 1),
        "formant_warp": round(alpha, 3),
        "breathiness": round(float(breath), 2),
    })
    return y, sr, report


def shift_pitch(x: np.ndarray, sr: int, semitones: float = 0.0, pitch_range: float = 1.0) -> tuple[np.ndarray, int, dict]:
    """Apply the director's pitch offset and intonation range to an engine that has no pitch
    control (Piper, Sherpa). The voice keeps its own register and vocal tract: only F0 moves."""
    from .audio import resample

    if x.size == 0 or (abs(semitones) < 0.05 and abs(pitch_range - 1.0) < 0.02):
        return x, sr, {"applied": False}
    if sr != WORK_SR:
        x = resample(x, sr, WORK_SR)
        sr = WORK_SR
    peak = float(np.max(np.abs(x))) or 1.0
    f0, sp, ap = world_features(x / peak * 0.9, sr)
    voiced = f0 > 0
    if voiced.sum() < 5:
        return x, sr, {"applied": False}
    lf0 = np.log(f0[voiced])
    mu = lf0.mean()
    f0[voiced] = np.exp((lf0 - mu) * pitch_range + mu + np.log(2.0) * semitones / 12.0)
    y = pw.synthesize(f0, sp, ap, sr, frame_period=FRAME_MS)[: x.size]
    y = y / (np.max(np.abs(y)) + 1e-9) * peak
    return y, sr, {"applied": True, "semitones": round(semitones, 2), "range": round(pitch_range, 3)}
