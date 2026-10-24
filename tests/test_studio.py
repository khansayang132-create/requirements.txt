"""Tests for studio/studio_ai.py: the access-code gate and the AI call path.

Original request: the owner asked for an LSKhan app built with jac-shadcn. jaclang 0.16.7 serves
on 0.0.0.0 regardless of --host, so the app's AI calls are gated by STUDIO_ACCESS_CODE, which must
fail closed like TELEGRAM_ADMIN_ID. The AI itself is a local stub (no network).
"""
import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import dotenv
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "studio"))

ENV_VARS = ("STUDIO_ACCESS_CODE", "OMNIROUTE_API_KEY", "OMNIROUTE_BASE_URL", "OMNIROUTE_MODEL",
            "OPENAI_API_KEY", "OPENAI_MODEL", "HEADROOM_BASE_URL")


class StubAI(BaseHTTPRequestHandler):
    """OpenAI-compatible chat endpoint that records each prompt."""
    prompts: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StubAI.prompts.append(body["messages"][0]["content"])
        data = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                           "choices": [{"index": 0, "finish_reason": "stop",
                                        "message": {"role": "assistant", "content": " Hook satu "}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def stub_url():
    server = HTTPServer(("127.0.0.1", 0), StubAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


@pytest.fixture
def load_studio(monkeypatch):
    """Import studio_ai (and bot) fresh with exactly the given env, ignoring any local .env file."""
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr("time.sleep", lambda s: None)

    def _load(**env):
        for name in ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        for mod in ("bot", "studio_ai"):
            sys.modules.pop(mod, None)
        StubAI.prompts.clear()
        return importlib.import_module("studio_ai")
    return _load


def test_unset_code_locks_everyone(load_studio, stub_url):
    studio = load_studio(OMNIROUTE_API_KEY="k", OMNIROUTE_BASE_URL=stub_url)
    for code in ("", "anything"):
        assert studio.generate("hook", "topik", "", code) == {"ok": False, "error": studio.LOCKED}
        assert studio.status(code)["access"] is False
    assert studio.status("")["locked"] is True
    assert StubAI.prompts == []


@pytest.mark.parametrize("code", ["", "salah", "rahasia-panjang "])
def test_wrong_code_spends_nothing(load_studio, stub_url, code):
    studio = load_studio(STUDIO_ACCESS_CODE="rahasia-panjang", OMNIROUTE_API_KEY="k", OMNIROUTE_BASE_URL=stub_url)
    out = studio.generate("hook", "topik", "", code)
    assert out["ok"] is False and StubAI.prompts == []


def test_right_code_calls_ai_with_persona_task_and_angle(load_studio, stub_url):
    studio = load_studio(STUDIO_ACCESS_CODE="rahasia", OMNIROUTE_API_KEY="k", OMNIROUTE_BASE_URL=stub_url,
                         OMNIROUTE_MODEL="stub")
    assert studio.status("rahasia") == {"access": True, "error": "", "locked": False, "ai": True}
    out = studio.generate("script", "makan bareng keluarga suami", "lucu", "rahasia")
    assert out == {"ok": True, "text": "Hook satu"}
    prompt = StubAI.prompts[-1]
    assert prompt.startswith(studio.bot.CINTA_PERSONA)
    assert studio.bot.script_task("makan bareng keluarga suami") in prompt
    assert studio.ANGLES["lucu"] in prompt
    # A second call reuses the same event loop and HTTP pool.
    assert studio.generate("caption", "", "", "rahasia")["ok"] is True
    assert studio.bot.DEFAULT_TOPIC in StubAI.prompts[-1]


def test_rejects_bad_input_before_calling_ai(load_studio, stub_url):
    studio = load_studio(STUDIO_ACCESS_CODE="c", OMNIROUTE_API_KEY="k", OMNIROUTE_BASE_URL=stub_url)
    assert studio.generate("ddos", "x", "", "c")["ok"] is False
    assert studio.generate("hook", "x" * (studio.MAX_TOPIC + 1), "", "c")["ok"] is False
    assert StubAI.prompts == []


def test_no_ai_configured(load_studio):
    studio = load_studio(STUDIO_ACCESS_CODE="c")
    assert studio.status("c")["ai"] is False
    assert "OMNIROUTE_API_KEY" in studio.generate("hook", "", "", "c")["error"]


def test_unreachable_ai_gives_a_friendly_error(load_studio):
    studio = load_studio(STUDIO_ACCESS_CODE="c", OMNIROUTE_API_KEY="k", OMNIROUTE_BASE_URL="http://127.0.0.1:9/v1")
    out = studio.generate("hook", "", "", "c")
    assert out["ok"] is False and "OmniRoute" in out["error"]
