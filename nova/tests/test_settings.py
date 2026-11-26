"""App settings (Settings page): AI server, encrypted key, test messages, voice install, toggles."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from nova import runtime
from nova.api import create_app

VOICE = b"fake-onnx-bytes" * 1000


class Server(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, json.dumps({"data": [{"id": "gemma4:e2b"}, {"id": "qwen"}]}).encode())
        elif self.path.endswith(".onnx"):
            self._send(200, VOICE, "application/octet-stream")
        elif self.path.endswith(".onnx.json"):
            self._send(200, b'{"audio": {"sample_rate": 22050}}')
        else:
            self._send(404, b"{}")

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        msg = {"role": "assistant", "content": "Hai, aku baik!"}
        self._send(200, json.dumps({"choices": [{"message": msg}]}).encode())


@pytest.fixture
def srv():
    s = HTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_llm_settings_saved_tested_and_key_hidden(settings, srv):
    c = TestClient(create_app(settings))
    assert c.get("/api/settings").json()["llm"]["provider"] == "off"
    r = c.post("/api/settings/llm/models", json={"base_url": srv}).json()
    assert r["ok"] and r["models"] == ["gemma4:e2b", "qwen"]
    saved = c.put("/api/settings/llm", json={"provider": "ollama", "base_url": srv + "/v1", "model": "gemma4:e2b",
                                             "api_key": "sk-secret-123", "thinking": False}).json()
    assert saved["llm"]["base_url"] == srv + "/v1" and saved["llm"]["api_key_set"] is True
    assert "sk-secret-123" not in json.dumps(saved)
    raw = (settings.data_dir / "runtime.json").read_text()
    assert "sk-secret-123" not in raw and oct((settings.data_dir / "runtime.json").stat().st_mode)[-3:] == "600"
    t = c.post("/api/settings/llm/test").json()
    assert t["ok"] and t["reply"] == "Hai, aku baik!"
    assert c.get("/api/system").json()["llm"]["configured"] is True
    # A fresh app instance reads the saved settings back.
    c2 = TestClient(create_app(settings.__class__()))
    assert c2.get("/api/settings").json()["llm"]["model"] == "gemma4:e2b"
    off = c2.put("/api/settings/llm", json={"provider": "off"}).json()
    assert off["llm"]["base_url"] == "" and c2.post("/api/settings/llm/test").json()["ok"] is False


def test_llm_errors_are_explained(settings):
    c = TestClient(create_app(settings))
    assert c.put("/api/settings/llm", json={"provider": "custom", "base_url": "file:///etc/passwd"}).status_code == 422
    assert c.put("/api/settings/llm", json={"provider": "nope", "base_url": "http://x"}).status_code == 422
    c.put("/api/settings/llm", json={"provider": "llama.cpp", "base_url": "http://127.0.0.1:9", "model": "m"})
    t = c.post("/api/settings/llm/test").json()
    assert t["ok"] is False and "Can't reach the server" in t["error"]


def test_piper_voice_install_from_app(settings, srv, monkeypatch, tmp_path):
    monkeypatch.setitem(runtime.PIPER_VOICE, "base", srv + "/voice")
    monkeypatch.setitem(runtime.PIPER_VOICE, "sha256", hashlib.sha256(VOICE).hexdigest())
    settings.piper_model = str(tmp_path / "models" / runtime.PIPER_VOICE["file"])
    c = TestClient(create_app(settings))
    job = c.post("/api/voices/piper/install").json()["job_id"]
    import time
    for _ in range(100):
        j = c.get(f"/api/jobs/{job}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j["status"] == "done", j["error"]
    assert c.get("/api/settings").json()["piper"]["installed"] is True
    monkeypatch.setitem(runtime.PIPER_VOICE, "sha256", "0" * 64)  # a corrupted download installs nothing
    (tmp_path / "models" / runtime.PIPER_VOICE["file"]).unlink()
    job = c.post("/api/voices/piper/install").json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/jobs/{job}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j["status"] == "failed" and "checksum" in j["error"]
    assert not (tmp_path / "models" / runtime.PIPER_VOICE["file"]).exists()


def test_chatterbox_toggle_requires_install(settings, monkeypatch):
    monkeypatch.setattr(runtime, "_chatterbox_installed", lambda: False)
    c = TestClient(create_app(settings))
    assert c.put("/api/settings/chatterbox", json={"enabled": True}).status_code == 409
    assert c.put("/api/settings/chatterbox", json={"enabled": False}).json()["chatterbox"]["enabled"] is False
