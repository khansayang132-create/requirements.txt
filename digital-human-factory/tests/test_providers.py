"""Provider adapters against mocked HTTP / fake SDK clients. Nothing here reaches a real API or spends anything."""

import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from dhfactory.errors import ProviderNotConfigured
from dhfactory.providers.base import REGISTRY, get_provider
from dhfactory.utils.redaction import redact


def test_every_paid_provider_refuses_without_credentials(settings):
    get_provider("mock", settings)
    for name, cls in REGISTRY.items():
        if name in ("mock",):
            continue
        p = cls(settings)
        if p.env_var:
            with pytest.raises(ProviderNotConfigured) as e:
                p.require_key()
            assert p.env_var in str(e.value)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_heygen_generate_poll_download(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGEN_API_KEY", "hg_secret_123456")
    from dhfactory.config import Settings

    p = get_provider("heygen", Settings(_env_file=None, dhf_workspace=tmp_path))
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.host, req.headers.get("x-api-key")))
        if req.url.path == "/v2/user/remaining_quota":
            return httpx.Response(200, json={"data": {"remaining_quota": 600}})
        if req.url.path == "/v2/video/generate":
            body = json.loads(req.content)
            assert body["video_inputs"][0]["character"]["avatar_id"] == "av1"
            assert body["dimension"] == {"width": 1080, "height": 1920}
            return httpx.Response(200, json={"data": {"video_id": "vid42"}})
        if req.url.path == "/v1/video_status.get":
            return httpx.Response(200, json={"data": {"status": "completed", "video_url": "https://files.example/v.mp4"}})
        if req.url.host == "files.example":
            return httpx.Response(200, content=b"MP4DATA")
        return httpx.Response(404)

    c = _client(handler)
    assert p.health(client=c)["remaining_quota"] == 600
    out = tmp_path / "a.mp4"
    res = p.talking_video("Hello", None, out, (1080, 1920), 5, avatar_id="av1", voice_id="v1", client=c, sleep=lambda s: None)
    assert out.read_bytes() == b"MP4DATA" and res.provider_job_id == "vid42" and res.lip_sync == "provider"
    assert all(key == "hg_secret_123456" for host, key in seen if host == "api.heygen.com")
    assert all(key is None for host, key in seen if host != "api.heygen.com")   # the API key never goes to the file host


def test_heygen_rejected_key_is_blocked_not_success(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGEN_API_KEY", "bad")
    from dhfactory.config import Settings

    p = get_provider("heygen", Settings(_env_file=None, dhf_workspace=tmp_path))
    with pytest.raises(ProviderNotConfigured, match="401"):
        p.health(client=_client(lambda r: httpx.Response(401, json={"error": "nope"})))


def test_heygen_resume_does_not_resubmit(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGEN_API_KEY", "k" * 12)
    from dhfactory.config import Settings

    p = get_provider("heygen", Settings(_env_file=None, dhf_workspace=tmp_path))
    posts = []

    def handler(req):
        if req.method == "POST":
            posts.append(req.url.path)
        if req.url.path == "/v1/video_status.get":
            return httpx.Response(200, json={"data": {"status": "completed", "video_url": "https://f.example/x.mp4"}})
        return httpx.Response(200, content=b"X")

    p.talking_video("Hi", None, tmp_path / "x.mp4", (1080, 1920), 3, avatar_id="a", voice_id="v", client=_client(handler), sleep=lambda s: None,
                    resume_job_id="old-job")
    assert posts == []


def test_did_and_synthesia_shapes(monkeypatch, tmp_path):
    monkeypatch.setenv("DID_API_KEY", "didkey123456")
    monkeypatch.setenv("SYNTHESIA_API_KEY", "synkey123456")
    from dhfactory.config import Settings

    s = Settings(_env_file=None, dhf_workspace=tmp_path)

    def did(req):
        if req.url.path == "/talks" and req.method == "POST":
            assert req.headers["authorization"] == "Basic didkey123456"
            assert json.loads(req.content)["script"]["type"] == "text"
            return httpx.Response(201, json={"id": "tlk"})
        if req.url.path == "/talks/tlk":
            return httpx.Response(200, json={"status": "done", "result_url": "https://r.example/t.mp4"})
        return httpx.Response(200, content=b"D")

    r = get_provider("did", s).talking_video("Hi", None, tmp_path / "d.mp4", (1080, 1920), 3, source_url="https://img.example/p.png",
                                            client=_client(did), sleep=lambda x: None)
    assert r.provider_job_id == "tlk"

    def syn(req):
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["test"] is True and body["aspectRatio"] == "9:16"
            return httpx.Response(201, json={"id": "s1"})
        if req.url.path == "/v2/videos/s1":
            return httpx.Response(200, json={"status": "complete", "download": "https://dl.example/s.mp4"})
        return httpx.Response(200, content=b"S")

    r = get_provider("synthesia", s).talking_video("Hi", None, tmp_path / "s.mp4", (1080, 1920), 3, avatar="anna", client=_client(syn),
                                                  sleep=lambda x: None)
    assert (tmp_path / "s.mp4").read_bytes() == b"S"


def test_elevenlabs_uses_provider_timings(monkeypatch, tmp_path):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg")
    import subprocess

    monkeypatch.setenv("ELEVENLABS_API_KEY", "el_key_123456")
    from dhfactory.config import Settings

    p = get_provider("elevenlabs", Settings(_env_file=None, dhf_workspace=tmp_path))
    mp3 = tmp_path / "t.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1", str(mp3)], check=True)
    text = ["Hi there.", "Bye."]
    joined = " ".join(text)
    starts = [i * 0.05 for i in range(len(joined))]
    resp = SimpleNamespace(audio_base_64=base64.b64encode(mp3.read_bytes()).decode(),
                           alignment=SimpleNamespace(characters=list(joined), character_start_times_seconds=starts,
                                                     character_end_times_seconds=[s + 0.05 for s in starts]))
    fake = SimpleNamespace(text_to_speech=SimpleNamespace(convert_with_timestamps=lambda **kw: resp))
    res = p.tts(text, tmp_path / "voice.wav", voice_id="voice1", client=fake)
    assert res.timing_source == "provider" and res.cues[0] == {"text": "Hi there.", "start": 0.0, "end": 0.45}
    assert res.cues[1]["start"] == pytest.approx(0.5)


def test_elevenlabs_refuses_unauthorized_clone(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el_key_123456")
    from dhfactory.config import Settings
    from dhfactory.errors import DHFError

    p = get_provider("elevenlabs", Settings(_env_file=None, dhf_workspace=tmp_path))
    with pytest.raises(DHFError, match="authorization"):
        p.tts(["x"], tmp_path / "v.wav", voice_id="clone:someone", authorized_clones=set(), client=object())


def test_runway_image_to_video_with_fake_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNWAYML_API_SECRET", "rw_key_123456")
    from dhfactory.config import Settings
    from dhfactory.providers import _http

    monkeypatch.setattr(_http, "download", lambda url, out, **kw: out.write_bytes(b"RW") or out)
    p = get_provider("runway", Settings(_env_file=None, dhf_workspace=tmp_path))
    img = tmp_path / "i.png"
    img.write_bytes(b"\x89PNG")
    calls = {}
    fake = SimpleNamespace(
        image_to_video=SimpleNamespace(create=lambda **kw: calls.setdefault("create", kw) and SimpleNamespace(id="t1")),
        tasks=SimpleNamespace(retrieve=lambda i: SimpleNamespace(status="SUCCEEDED", output=["https://o.example/v.mp4"])))
    res = p.image_to_video(img, "push in", tmp_path / "v.mp4", client=fake, sleep=lambda s: None)
    assert calls["create"]["prompt_image"].startswith("data:image/png;base64,") and res.provider_job_id == "t1"


def test_redaction_hides_keys(monkeypatch):
    monkeypatch.setenv("HEYGEN_API_KEY", "supersecretvalue99")
    assert "supersecretvalue99" not in redact("failed with key supersecretvalue99")
    assert "***" in redact('{"x-api-key": "abc123def"}')
