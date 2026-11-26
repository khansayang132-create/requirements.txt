"""Neural cloning end to end. Heavy (~3 GB weights, minutes on CPU), so it runs only with
NOVA_CHATTERBOX_TEST=1 and requirements-neural.txt installed."""
import importlib.util
import os
import time

import numpy as np
import pytest
from conftest import CONSENT, PIPER_MODEL
from fastapi.testclient import TestClient

from nova.analysis import analyze_voice
from nova.api import create_app
from nova.audio import load_audio, write_wav
from nova.tts import PiperEngine, Prosody

pytestmark = pytest.mark.skipif(
    os.environ.get("NOVA_CHATTERBOX_TEST") != "1" or importlib.util.find_spec("chatterbox") is None
    or not PIPER_MODEL.is_file(), reason="neural cloning test not enabled")


def test_chatterbox_clones_reference_voice(settings, tmp_path):
    # Reference: a synthetic female voice (Piper), so no real person's voice is used.
    e = PiperEngine(str(PIPER_MODEL))
    text = ("Halo, nama saya Test Speaker. Saya merekam suara ini dengan tenang dan jelas, supaya studio bisa "
            "mempelajari cara saya berbicara. Terima kasih sudah mendengarkan rekaman saya hari ini.")
    x, sr = e.synthesize(text, "id", Prosody(rate=0.9))
    ref_pitch = analyze_voice(np.concatenate([x, x]), sr)["pitch"]["f0_median_hz"]
    wav = write_wav(tmp_path / "ref.wav", x * 0.8, sr)

    settings.chatterbox = True
    c = TestClient(create_app(settings))
    with open(wav, "rb") as fh:
        p = c.post("/api/profiles", data=CONSENT | {"language": "id"}, files={"audio": ("ref.wav", fh, "audio/wav")}).json()
    job = c.post("/api/generate", json={"text": "Ada satu hal tentang keluarga suamiku yang tidak pernah aku bayangkan.",
                                         "profile_id": p["id"], "engine": "chatterbox-id", "formats": ["wav"]}).json()
    for _ in range(3000):
        j = c.get(f"/api/jobs/{job['job_id']}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(1)
    assert j["status"] == "done", j["error"]
    res = j["result"]
    s0 = res["sentences"][0]
    assert res["engine"] == "chatterbox-id" and s0["voice"] == "profile reference (neural clone)"
    assert s0["conversion"] == []  # identity came from the neural clone, not WORLD
    y, ysr = load_audio(res["files"]["wav"]["path"])
    out_pitch = analyze_voice(np.concatenate([y, y]), ysr)["pitch"]["f0_median_hz"]
    print(f"reference {ref_pitch:.0f} Hz -> clone {out_pitch:.0f} Hz")
    assert out_pitch > 170 and abs(out_pitch - ref_pitch) < 60  # default voice is ~114 Hz
