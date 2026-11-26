"""LLM client against a fake OpenAI-compatible server (no model needed), plus an opt-in run
against a real one: NOVA_LLM_TEST_URL=http://127.0.0.1:8093 (llama-server, Ollama, LM Studio)."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nova.config import Settings
from nova.enhance import enhance
from nova.llm import LLMClient, LLMEmpty, _base_url


class Fake(BaseHTTPRequestHandler):
    calls: list = []
    reply = "Halo."
    reject_kwargs = False
    reasoning_only = False

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.calls.append({"path": self.path, "body": body})
        if Fake.reject_kwargs and "chat_template_kwargs" in body:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"Unrecognized request argument"}')
            return
        msg = {"role": "assistant", "content": "" if Fake.reasoning_only else Fake.reply}
        if Fake.reasoning_only:
            msg["reasoning_content"] = "Thinking Process: ..."
        data = json.dumps({"choices": [{"message": msg, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake():
    Fake.calls, Fake.reply, Fake.reject_kwargs, Fake.reasoning_only = [], "Halo.", False, False
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def client(url, monkeypatch):
    monkeypatch.setenv("NOVA_LLM_BASE_URL", url)
    monkeypatch.delenv("NOVA_LLM_THINKING", raising=False)
    return LLMClient.from_settings(Settings())


def test_base_url_forms():
    for u in ("http://h:1", "http://h:1/", "http://h:1/v1", "http://h:1/v1/chat/completions"):
        assert _base_url(u) == "http://h:1/v1"


def test_thinking_off_by_default_and_retry_without_it(fake, monkeypatch):
    c = client(fake, monkeypatch)
    assert c.notes("Halo semua.") == "Halo."
    assert Fake.calls[-1]["path"] == "/v1/chat/completions"
    assert Fake.calls[-1]["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    Fake.reject_kwargs = True
    assert c.notes("Halo semua.") == "Halo."
    assert "chat_template_kwargs" not in Fake.calls[-1]["body"]


def test_reasoning_only_reply_is_not_used(fake, monkeypatch):
    Fake.reasoning_only = True
    with pytest.raises(LLMEmpty):
        client(fake, monkeypatch).rewrite("Halo.", "natural", "id")
    r = enhance("aku kira menikah beda negara cuma soal cinta. ternyata aku salah.", "natural",
                client(fake, monkeypatch))
    assert r["source"] == "rules" and r["llm"] == {"accepted": False, "error": "LLMEmpty"}


def test_meaning_gate_accepts_and_rejects(fake, monkeypatch):
    c = client(fake, monkeypatch)
    text = "aku kira menikah beda negara cuma soal cinta. ternyata aku salah."
    Fake.reply = "Aku kira menikah beda negara cuma soal cinta. Ternyata, aku salah."
    assert enhance(text, "natural", c)["source"] == "llm+rules"
    Fake.reply = "Beli sepatu murah hari ini di toko kami, diskon besar!"
    r = enhance(text, "natural", c)
    assert r["source"] == "rules" and r["llm"]["accepted"] is False
    assert "sepatu" not in r["enhanced"]


@pytest.mark.skipif(not os.environ.get("NOVA_LLM_TEST_URL"), reason="no real LLM server given")
def test_real_local_llm(monkeypatch):
    c = client(os.environ["NOVA_LLM_TEST_URL"], monkeypatch)
    out = c.rewrite("um aku kira menikah beda negara cuma soal cinta. ternyata aku salah.", "natural", "id")
    assert out and "menikah" in out.lower()
    r = enhance("um aku kira menikah beda negara cuma soal cinta. ternyata aku salah.", "natural", c)
    assert r["meaning"]["preserved"]
