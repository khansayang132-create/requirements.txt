"""Runs only when the Indonesian Piper voice is installed (scripts/get-voices.sh)."""
import time

import numpy as np
import pytest
from conftest import ID_SCRIPT, PIPER_MODEL
from fastapi.testclient import TestClient

from nova.analysis import analyze_voice
from nova.api import create_app
from nova.audio import load_audio, probe
from nova.clone import shift_pitch
from nova.tts import PiperEngine, Prosody

pytestmark = pytest.mark.skipif(not PIPER_MODEL.is_file(), reason="Piper voice not installed")


def test_piper_indonesian_voice_and_rate():
    e = PiperEngine(str(PIPER_MODEL))
    text = "Ada satu hal tentang keluarga suamiku yang tidak pernah aku bayangkan."
    x, sr = e.synthesize(text, "id", Prosody())
    assert sr == 22050 and x.size / sr > 2
    # Piper randomises timing on every render (noise_w), so compare medians of three takes.
    normal = np.median([e.synthesize(text, "id", Prosody())[0].size for _ in range(3)])
    slow = np.median([e.synthesize(text, "id", Prosody(rate=0.8))[0].size for _ in range(3)])
    assert slow > normal * 1.08  # rate 0.8 -> length_scale 1.25; measured 1.13-1.20, no effect ~1.0
    assert 170 < analyze_voice(np.concatenate([x, x]), sr)["pitch"]["f0_median_hz"] < 320  # female speaker


def test_pitch_shift_for_engines_without_pitch():
    x, sr = PiperEngine(str(PIPER_MODEL)).synthesize("Akhirnya kami bisa menunjukkan sesuatu yang baru.", "id", Prosody())
    up, usr, rep = shift_pitch(x, sr, 3.0, 1.4)
    a = analyze_voice(np.concatenate([x, x]), sr)["pitch"]
    b = analyze_voice(np.concatenate([up, up]), usr)["pitch"]
    assert rep["applied"] and b["f0_median_hz"] / a["f0_median_hz"] > 1.12
    assert b["range_semitones"] > a["range_semitones"]


def test_generate_with_piper(settings):
    settings.piper_model = str(PIPER_MODEL)
    c = TestClient(create_app(settings))
    pid = c.post("/api/profiles/design", json={"preset": "soft-young-indonesian-woman"}).json()["id"]
    job = c.post("/api/generate", json={"text": ID_SCRIPT, "profile_id": pid, "mode": "expressive", "formats": ["wav", "mp3"]}).json()
    for _ in range(400):
        j = c.get(f"/api/jobs/{job['job_id']}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.3)
    assert j["status"] == "done", j["error"]
    res = j["result"]
    assert res["engine"] == "piper"
    assert res["sentences"][0]["applied_by"]["rate"] == "engine"
    assert res["sentences"][0]["applied_by"]["emphasis"] == "not supported"
    for fmt in ("wav", "mp3"):
        assert probe(res["files"][fmt]["path"])["duration"] > 5
    x, sr = load_audio(res["files"]["wav"]["path"])
    assert abs(analyze_voice(x, sr)["pitch"]["f0_median_hz"] - 228) < 30
