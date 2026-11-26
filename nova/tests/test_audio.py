import re
import subprocess

import numpy as np

from nova.analysis import analyze_voice
from nova.audio import export, load_audio, probe, write_wav
from nova.clone import convert
from nova.mastering import integrated_loudness, master, true_peak_db
from nova.profiles import designed_voice
from nova.tts import EspeakEngine, Prosody


def _ffmpeg_lufs(path) -> float:
    err = subprocess.run(["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?\d+\.\d) LUFS", err)[-1])


def test_loudness_matches_ffmpeg(tmp_path, speaker_wav):
    x, sr = load_audio(speaker_wav)
    path = write_wav(tmp_path / "a.wav", x * 0.3, sr)
    assert abs(integrated_loudness(x * 0.3, sr) - _ffmpeg_lufs(path)) < 0.3


def test_master_hits_target_and_ceiling(tmp_path, speaker_wav):
    x, sr = load_audio(speaker_wav)
    y, out_sr, rep = master(x * 0.05, sr, target_sr=44100, target_lufs=-16)
    assert out_sr == 44100
    assert abs(rep["output_lufs"] + 16) < 1.0
    assert true_peak_db(y) <= -0.9
    path = export(tmp_path / "m.wav", y, out_sr, "wav")
    assert abs(_ffmpeg_lufs(path) + 16) < 1.0


def test_noise_reduction_only_when_needed(speaker_wav):
    x, sr = load_audio(speaker_wav)
    _, _, clean = master(x, sr)
    assert clean["noise_reduction"]["applied"] is False
    noisy = x + np.random.default_rng(0).normal(0, 0.01, x.size)
    _, _, rep = master(noisy, sr)
    assert rep["noise_reduction"]["applied"] is True


def test_voice_analysis_measures(speaker_wav):
    x, sr = load_audio(speaker_wav)
    a = analyze_voice(x, sr, "en", "American")
    assert 150 < a["pitch"]["f0_median_hz"] < 320  # espeak female variant
    assert a["speed"]["estimated_wpm"] > 60
    assert a["rhythm"]["pause_count"] >= 2
    assert a["accent"]["source"].startswith("declared")
    for key in ("pitch", "depth", "texture", "tone", "speed", "energy", "rhythm", "emotion", "pronunciation"):
        assert key in a


def test_conversion_moves_pitch_to_profile():
    x, sr = EspeakEngine().synthesize("This sentence is spoken by the base voice for conversion.", "en",
                                      Prosody(), "en-us+m3")
    target = designed_voice({"pitch_hz": 220, "formant_scale_hz": 1420})
    y, ysr, rep = convert(x, sr, target)
    out = analyze_voice(np.concatenate([y, y]), ysr)
    assert abs(out["pitch"]["f0_median_hz"] - 220) < 25
    y2, _, rep2 = convert(x, sr, target, pitch_semitones=4)
    assert rep2["target_f0_hz"] > rep["target_f0_hz"] * 1.2


def test_mp3_and_wav_export_verified(tmp_path):
    x = np.sin(2 * np.pi * 220 * np.arange(48000) / 48000) * 0.3
    for fmt, codec in (("wav", "pcm_s16le"), ("mp3", "mp3")):
        info = probe(export(tmp_path / f"t.{fmt}", x, 48000, fmt))
        assert info["codec"] == codec and info["sample_rate"] == 48000 and abs(info["duration"] - 1) < 0.1


def test_time_stretch_changes_speed_not_pitch(speaker_wav):
    from nova.audio import time_stretch
    x, sr = load_audio(speaker_wav)
    y = time_stretch(x, sr, 1.25)
    assert abs(y.size / x.size - 0.8) < 0.03
    a, b = analyze_voice(x, sr), analyze_voice(y, sr)
    assert abs(b["pitch"]["f0_median_hz"] - a["pitch"]["f0_median_hz"]) < 10


def _f0(x, sr):
    import pyworld as pw
    f0, _ = pw.harvest(x.astype(np.float64), sr, f0_floor=70, f0_ceil=600, frame_period=10)
    return float(np.median(f0[f0 > 0]))


def test_voice_tone_pitch_and_soften(speaker_wav):
    from nova.audio import load_audio, voice_tone
    x, sr = load_audio(speaker_wav, sr=24000)
    x = x[: sr * 6]
    up = voice_tone(x, sr, pitch_semitones=2.0)
    assert up.size == x.size
    ratio = _f0(up, sr) / _f0(x, sr)
    assert abs(12 * np.log2(ratio) - 2.0) < 0.5  # about two semitones higher
    soft = voice_tone(x, sr, soften=1.0)
    spec = lambda y: np.abs(np.fft.rfft(y))
    fr = np.fft.rfftfreq(x.size, 1 / sr)
    hi = lambda y: spec(y)[fr > 7000].sum() / spec(y).sum()
    assert soft.size == x.size and hi(soft) < hi(x)  # softer highs
    # soften moves the formants, not the pitch (-0.18 st on a real cloned voice; the pitch tracker
    # reads up to ~0.7 st on this flat synthetic voice once its formants move)
    assert abs(12 * np.log2(_f0(soft, sr) / _f0(x, sr))) < 0.8
    assert voice_tone(x, sr) is x  # nothing asked, nothing done
