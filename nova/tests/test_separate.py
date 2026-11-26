"""Opt-in: needs the neural install (torch, onnxruntime) and the UVR model in NOVA_UVR_MODELS_DIR."""
import os
from pathlib import Path

import numpy as np
import pytest

MODELS = Path(os.environ.get("NOVA_UVR_MODELS_DIR", Path.home() / ".nova" / "models"))
pytest.importorskip("torch")
pytest.importorskip("onnxruntime")
if not (MODELS / "UVR-MDX-NET-Voc_FT.onnx").is_file():
    pytest.skip("UVR model not downloaded", allow_module_level=True)


def test_voice_comes_out_of_the_music(tmp_path, speaker_wav):
    from nova.audio import load_audio, write_wav
    from nova.separate import separate
    voice, sr = load_audio(speaker_wav, sr=44100)
    t = np.arange(voice.size) / sr
    music = 0.25 * (np.sin(2 * np.pi * 110 * t) + 0.5 * np.sin(2 * np.pi * 220 * t + 1)) * (1 + 0.3 * np.sin(2 * np.pi * 2 * t))
    mix = write_wav(tmp_path / "mix.wav", 0.6 * voice + music, sr)
    out, rest, osr = separate(mix, MODELS)
    v = out.mean(0)[: voice.size]
    corr = lambda a, b: float(np.corrcoef(a, b)[0, 1])
    assert osr == 44100
    assert corr(v, voice) > 0.9 > corr(0.6 * voice + music, voice)  # the separated track is the voice
    assert corr(rest.mean(0)[: music.size], music) > 0.9
