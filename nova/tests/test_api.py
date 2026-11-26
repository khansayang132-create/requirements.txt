import time

import pytest
from conftest import CONSENT, EN_SCRIPT, ID_SCRIPT, MIXED_SCRIPT
from fastapi.testclient import TestClient

from nova.api import create_app
from nova.audio import probe


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def _upload(client, wav, **overrides):
    data = CONSENT | {"name": "My Voice", "language": "en", "accent": "American"} | overrides
    with open(wav, "rb") as fh:
        return client.post("/api/profiles", data=data, files={"audio": ("speaker.wav", fh, "audio/wav")})


def _wait(client, job_id, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.3)
    raise AssertionError("job timed out")


def test_health_and_system(client):
    assert client.get("/api/health").json()["status"] == "ok"
    sysinfo = client.get("/api/system").json()
    espeak = next(e for e in sysinfo["engines"] if e["name"] == "espeak-ng")
    assert espeak["available"] and espeak["controls"]["pitch"]
    assert any(p["id"] == "soft-young-indonesian-woman" for p in sysinfo["presets"])


def test_profile_requires_consent(client, speaker_wav):
    assert _upload(client, speaker_wav, consent_confirmed="false").status_code == 403
    assert _upload(client, speaker_wav, consent_statement="I agree to everything here ok.").status_code == 403
    assert _upload(client, speaker_wav, relationship="found online").status_code == 403
    assert client.get("/api/profiles").json() == []


def test_create_save_and_reload_profile(settings, speaker_wav):
    c1 = TestClient(create_app(settings))
    r = _upload(c1, speaker_wav)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["consent"]["audio_sha256"] and p["voice"]["pitch"]["f0_median_hz"] > 150
    files = list((settings.profiles_dir / p["id"]).iterdir())
    assert {f.name for f in files} == {"profile.json.enc", "reference.wav.enc"}
    assert b"Test Speaker" not in (settings.profiles_dir / p["id"] / "profile.json.enc").read_bytes()
    assert oct(files[0].stat().st_mode)[-3:] == "600"
    c2 = TestClient(create_app(settings))  # a fresh app instance reloads from disk
    assert [x["id"] for x in c2.get("/api/profiles").json()] == [p["id"]]
    assert c2.get(f"/api/profiles/{p['id']}").json()["voice"] == p["voice"]
    assert c2.delete(f"/api/profiles/{p['id']}").status_code == 200
    assert c2.get(f"/api/profiles/{p['id']}").status_code == 404


def test_designed_profile_and_preview(client):
    p = client.post("/api/profiles/design", json={"preset": "soft-young-indonesian-woman"}).json()
    assert p["kind"] == "designed" and p["consent"] is None
    url = client.post(f"/api/profiles/{p['id']}/preview", json={}).json()["url"]
    r = client.get(url)
    assert r.status_code == 200 and r.content[:4] == b"RIFF"


@pytest.mark.parametrize("text,lang", [(EN_SCRIPT, "en"), (ID_SCRIPT, "id")])
def test_analyze_endpoint(client, text, lang):
    r = client.post("/api/script/analyze", json={"text": text}).json()
    assert r["language"]["primary"] == lang and 0 <= r["score"] <= 100


def test_analyze_mixed_and_enhance_compare(client):
    assert client.post("/api/script/analyze", json={"text": MIXED_SCRIPT}).json()["language"]["is_mixed"]
    r = client.post("/api/script/enhance", json={"text": "um we have 3 products & they are are great", "mode": "professional"}).json()
    assert r["original"] != r["enhanced"] and r["diff"] and r["meaning"]["preserved"]
    assert r["enhanced_score"] >= r["original_score"]
    d = client.post("/api/script/direct", json={"text": r["enhanced"], "mode": "professional"}).json()
    assert d["directions"] and "[" in d["script"]


def test_generate_with_cloned_voice_wav_mp3(client, speaker_wav, settings):
    pid = _upload(client, speaker_wav).json()["id"]
    job = client.post("/api/generate", json={"text": EN_SCRIPT, "profile_id": pid, "mode": "professional",
                                             "formats": ["wav", "mp3"], "sample_rate": 44100,
                                             "pronunciation": {"NOVA": "no va"}}).json()
    done = _wait(client, job["job_id"])
    assert done["status"] == "done", done["error"]
    res = done["result"]
    assert res["profile"]["id"] == pid and res["engine"] == "espeak-ng"
    assert all(s["conversion"] for s in res["sentences"])
    assert abs(res["mastering"]["output_lufs"] + 16) < 1.0 and res["mastering"]["true_peak_dbtp"] <= -0.9
    for fmt, codec in (("wav", "pcm_s16le"), ("mp3", "mp3")):
        r = client.get(res["urls"][fmt])
        assert r.status_code == 200
        path = settings.outputs_dir / done["id"] / f"voiceover.{fmt}"
        info = probe(path)
        assert info["codec"] == codec and info["sample_rate"] == 44100 and info["duration"] > 5


def test_generate_multi_segment(client):
    pid = client.post("/api/profiles/design", json={"preset": "soft-young-indonesian-woman"}).json()["id"]
    segments = [
        {"label": "Intro", "text": "Selamat datang di cerita kami.", "emotion": "neutral"},
        {"label": "Presentation", "text": "Akhirnya kami bisa menunjukkan sesuatu yang baru!", "emotion": "excitement"},
        {"label": "Story", "text": "Aku masih ingat hari ketika aku harus pergi jauh dari keluarga.", "emotion": "sadness"},
        {"label": "Closing", "text": "Kamu harus berani memilih jalanmu sendiri.", "emotion": "authority"},
    ]
    done = _wait(client, client.post("/api/generate", json={"segments": segments, "profile_id": pid,
                                                           "mode": "expressive", "formats": ["mp3"]}).json()["job_id"])
    assert done["status"] == "done", done["error"]
    res = done["result"]
    assert [s["emotion"] for s in res["segments"]] == ["neutral", "excitement", "sadness", "authority"]
    rates = {s["tone"]: s["prosody"]["rate"] for s in res["sentences"]}
    assert rates["Excited tone"] > rates["Gentle, sad tone"]
    assert res["files"]["mp3"]["probe"]["duration"] > 8
    assert list(res["files"]) == ["mp3"]


def test_generate_validation(client):
    assert client.post("/api/generate", json={"text": "hi", "sample_rate": 12345}).status_code in (200, 422)
    assert client.post("/api/generate", json={}).status_code == 422
    assert client.post("/api/generate", json={"text": "hi", "profile_id": "0" * 32}).status_code == 404
    assert client.get("/api/files/../../etc/passwd").status_code == 404


def test_projects_crud(client):
    p = client.post("/api/projects", json={"name": "Episode 1", "data": {"script": ID_SCRIPT}}).json()
    assert client.get(f"/api/projects/{p['id']}").json()["data"]["script"] == ID_SCRIPT
    assert client.get("/api/projects").json()[0]["id"] == p["id"]
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200


def test_api_key_protects_routes(settings, monkeypatch):
    settings.api_key = "s3cret"
    c = TestClient(create_app(settings))
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/profiles").status_code == 401
    assert c.get("/api/profiles", headers={"Authorization": "Bearer s3cret"}).status_code == 200
