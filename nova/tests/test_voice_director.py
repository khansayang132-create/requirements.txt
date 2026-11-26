"""The /api/voice-director routes, called exactly as the NOVA Voice Studio Android app
(com.lskhan.nova, MainActivity.kt) calls them, and checked the way the app checks them."""
import pytest
from conftest import CONSENT
from fastapi.testclient import TestClient

from nova.api import create_app
from nova.audio import probe


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def _app_payload(voice_id, script, preset="natural", speed=1.0):
    # MainActivity.generateAudio(): speed = 0.5 + progress/100, preset lowercased, one segment.
    return {"filename": "nova_android_1764140000000", "voice_id": voice_id, "speed": speed, "preset": preset,
            "segments": [{"text": script, "pause_after_ms": 500}]}


def test_voices_lists_default_and_profiles(client, speaker_wav):
    voices = client.get("/api/voice-director/voices").json()["voices"]
    assert [v["id"] for v in voices] == ["nova-default"] and voices[0]["available"] is True
    with open(speaker_wav, "rb") as fh:
        pid = client.post("/api/profiles", data=CONSENT | {"name": "My Voice", "language": "en"},
                          files={"audio": ("s.wav", fh, "audio/wav")}).json()["id"]
    voices = client.get("/api/voice-director/voices").json()["voices"]
    mine = [v for v in voices if v["id"] == pid]
    assert mine and mine[0]["name"] == "My Voice" and mine[0]["available"] is True


@pytest.mark.parametrize("preset", ["natural", "energetic"])
def test_produce_returns_a_wav_the_app_accepts(client, settings, preset):
    r = client.post("/api/voice-director/produce",
                    json=_app_payload("nova-default", "Hello from the Android app. This is a test.", preset, 1.2))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["filename"] == "nova_android_1764140000000.wav"
    audio = client.get(body["audio_url"])
    assert audio.status_code == 200
    data = audio.content
    assert len(data) >= 44 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"  # MainActivity.isWaveFile
    info = probe(settings.outputs_dir / body["job_id"] / "voiceover.wav")
    assert abs(info["duration"] - body["duration"]) < 0.05 and body["duration"] > 1.0
    assert body["sample_rate"] == 48000


def test_produce_errors_carry_detail(client):
    unknown = client.post("/api/voice-director/produce", json=_app_payload("0" * 32, "Hello."))
    assert unknown.status_code == 404 and "detail" in unknown.json()
    bad_preset = client.post("/api/voice-director/produce", json=_app_payload("nova-default", "Hi.", "loud"))
    assert bad_preset.status_code == 422 and "loud" in bad_preset.json()["detail"]
    too_long = client.post("/api/voice-director/produce", json=_app_payload("nova-default", "a" * 5001))
    assert too_long.status_code == 422


def test_segment_pause_is_honoured(client, settings):
    def dur(pause):
        p = {"filename": "p", "voice_id": "nova-default", "speed": 1.0, "preset": "natural",
             "segments": [{"text": "First part.", "pause_after_ms": pause}, {"text": "Second part.", "pause_after_ms": 0}]}
        return client.post("/api/voice-director/produce", json=p).json()["duration"]
    # mastering caps any silence at 1.6 s, so stay below that
    assert dur(1300) - dur(100) > 0.8
