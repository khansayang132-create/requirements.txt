"""Master an uploaded voiceover: loudness to target, peaks limited, voice not converted, upload not kept."""
import time

from fastapi.testclient import TestClient

from nova.api import create_app
from nova.audio import load_audio, probe, write_wav


def _wait(c, job_id):
    for _ in range(300):
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.1)
    raise AssertionError("job timed out")


def test_master_uploaded_voiceover(settings, speaker_wav, tmp_path):
    x, sr = load_audio(speaker_wav)
    quiet = write_wav(tmp_path / "quiet.wav", x * 0.08, sr)  # well below social loudness
    c = TestClient(create_app(settings))
    with open(quiet, "rb") as fh:
        r = c.post("/api/master", data={"target_lufs": "-14", "formats": "wav,mp3"},
                   files={"audio": ("my-voiceover.wav", fh, "audio/wav")})
    j = _wait(c, r.json()["job_id"])
    assert j["status"] == "done", j["error"]
    res = j["result"]
    assert res["kind"] == "master" and res["source"] == "my-voiceover.wav"
    assert res["before"]["lufs"] < -24
    assert abs(res["mastering"]["output_lufs"] + 14) < 1.0 and res["mastering"]["true_peak_dbtp"] <= -0.9
    assert res["mastering"]["noise_reduction"]["applied"] is False  # clean source is left alone
    assert abs(res["mastering"]["duration_s"] - res["before"]["duration_s"]) < 0.5
    for fmt, codec in (("wav", "pcm_s16le"), ("mp3", "mp3")):
        assert c.get(res["urls"][fmt]).status_code == 200
        assert probe(res["files"][fmt]["path"])["codec"] == codec
    assert not list(settings.outputs_dir.glob("upload-*"))  # the upload itself is deleted


def test_master_rejects_bad_input(settings, tmp_path):
    c = TestClient(create_app(settings))
    (tmp_path / "x.wav").write_bytes(b"not audio")
    with open(tmp_path / "x.wav", "rb") as fh:
        assert c.post("/api/master", data={"target_lufs": "-40"}, files={"audio": ("x.wav", fh)}).status_code == 422
    with open(tmp_path / "x.wav", "rb") as fh:
        j = _wait(c, c.post("/api/master", files={"audio": ("x.wav", fh)}).json()["job_id"])
    assert j["status"] == "failed" and "decode" in j["error"]
