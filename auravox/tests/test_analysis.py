import numpy as np

from auravox import analysis
from auravox.engines.base import SR, write_wav


def tone(sec, f=200, amp=0.3, sr=SR):
    t = np.arange(int(sec * sr)) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def codes(m):
    return {d["code"] for d in m["defects"]}


def test_clean_signal_has_no_defects(tmp_path):
    x = np.concatenate([np.zeros(int(0.1 * SR)), tone(2.0), np.zeros(int(0.15 * SR))])
    m = analysis.measure(write_wav(tmp_path / "a.wav", x))
    assert codes(m) == set() and m["score"] == 100


def test_detects_silence_clipping_cutoff_rate_and_noise(tmp_path):
    assert "silence" in codes(analysis.measure(write_wav(tmp_path / "s.wav", np.zeros(SR, np.float32))))
    assert "clipping" in codes(analysis.measure(write_wav(tmp_path / "c.wav", np.clip(tone(1, amp=2.0), -1, 1))))
    assert "abrupt_cutoff" in codes(analysis.measure(write_wav(tmp_path / "x.wav", np.concatenate([np.zeros(int(0.1 * SR)), tone(1)]))))
    assert "sample_rate" in codes(analysis.measure(write_wav(tmp_path / "r.wav", tone(1, sr=22050), 22050)))
    hiss = np.random.default_rng(0).standard_normal(SR * 2).astype(np.float32) * 0.01
    assert "noise" in codes(analysis.measure(write_wav(tmp_path / "n.wav", np.concatenate([np.zeros(4800), tone(1.0), np.zeros(9600)]) + hiss[:62400])))


def test_missing_words_are_flagged_by_duration(tmp_path):
    m = analysis.measure(write_wav(tmp_path / "short.wav", np.concatenate([np.zeros(4800), tone(0.4), np.zeros(4800)])),
                         text="This sentence has quite a lot of words in it, so it cannot fit in under half a second.", wpm=150)
    assert "too_short" in codes(m) and "too_short" in analysis.blocking(m)


def test_f0_estimate(tmp_path):
    assert abs(analysis.f0_median(write_wav(tmp_path / "f.wav", tone(1.0, f=220))) - 220) < 5
