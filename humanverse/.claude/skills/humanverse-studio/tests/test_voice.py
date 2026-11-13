import pytest

voice = pytest.importorskip("hvlib.voice")


def test_espeak_returns_audio_and_ordered_phonemes():
    try:
        x, ph = voice.synthesize("Look how high it goes!", {"espeak_voice": "en-us", "rate": 150, "pitch": 60})
    except voice.VoiceUnavailable:
        pytest.skip("eSpeak NG not installed")
    assert len(x) > voice.SR * 0.5 and float(abs(x).max()) > 0.3
    assert len(ph) >= 8
    assert all(a < b for a, b, _p in ph) and all(ph[i][0] <= ph[i + 1][0] for i in range(len(ph) - 1))
    assert ph[-1][1] <= len(x) / voice.SR + 0.05
