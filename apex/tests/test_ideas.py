"""Idea generation for the planner, plan approval, and Headroom-first routing for LLM calls."""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from apex.autopilot import AutopilotPolicy, run_plan
from apex.ideas import generate_ideas, is_duplicate
from apex.jobs import JobQueue
from apex.script_engine import FallbackProvider, OpenAICompatibleProvider, provider_from_env

APEX_ROOT = Path(__file__).resolve().parent.parent


def idea(topic, angle="emotional", hook="Aku kira nikah beda negara cuma soal cinta... ternyata aku salah", **kw):
    return {"topic": topic, "angle": angle, "hook": hook, "target_seconds": 30,
            "call_to_action": "Kalau kamu di posisi aku, kamu tetap lanjut atau mundur?", **kw}


class FakeLLM:
    name = "fake"

    def __init__(self, ideas):
        self.reply = json.dumps({"ideas": ideas})
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return "Berikut ide-idenya:\n```json\n" + self.reply + "\n```"


BATCH = [
    idea("Hal kecil di keluarga Pakistan yang awalnya membuatku bingung", "cultural"),
    idea("Reaksi keluargaku waktu aku memilih suami dari Pakistan", "family"),
    idea("Halo guys hari ini cerita masak", "funny", hook="Halo guys, hari ini aku mau cerita soal masak"),
    idea("Tips judi online untuk pasangan beda negara", "educational"),
    idea("Hal kecil di keluarga Pakistan yang awalnya membuat aku bingung", "cultural"),  # near-duplicate
    idea("Kalau harus memilih tinggal di Indonesia atau Pakistan", "debate"),
    idea("Pertama kali makan biryani buatan ibu mertua", "funny"),
    idea("Yang tidak terlihat di foto pernikahan beda negara", "reality", target_seconds=400),
]


def test_review_rejects_greeting_banned_duplicate_and_invalid(tmp_path):
    plan = tmp_path / "plan.json"
    out = generate_ideas(FakeLLM(BATCH), plan, AutopilotPolicy(prohibited_topics=["judi"]), count=5)
    added = [e["spec"]["topic"] for e in out["added"]]
    assert added == [BATCH[0]["topic"], BATCH[1]["topic"], BATCH[5]["topic"], BATCH[6]["topic"]]
    reasons = json.dumps(out["rejected"], ensure_ascii=False)
    assert "slow greeting" in reasons and "prohibited keyword 'judi'" in reasons and "too similar" in reasons
    assert "less than or equal to 90" in reasons  # target_seconds=400
    saved = json.loads(plan.read_text())
    assert len(saved) == 4 and all(e["approved"] is False for e in saved)


def test_ideas_never_enqueue_until_approved(tmp_path):
    plan = tmp_path / "plan.json"
    generate_ideas(FakeLLM(BATCH[:2]), plan, AutopilotPolicy(), count=2)
    q = JobQueue(tmp_path / "jobs.db")
    decisions = run_plan(json.loads(plan.read_text()), q, AutopilotPolicy(), tmp_path)
    assert {d["decision"] for d in decisions} == {"WAITING_FOR_APPROVAL"} and q.counts() == {}


def test_second_batch_avoids_existing_topics_and_queue(tmp_path):
    plan = tmp_path / "plan.json"
    q = JobQueue(tmp_path / "jobs.db")
    q.enqueue("k", "produce_video", {"spec": {"topic": "Pertama kali makan biryani buatan ibu mertua"}})
    generate_ideas(FakeLLM(BATCH[:1]), plan, AutopilotPolicy(), count=1, queue=q)
    llm = FakeLLM([BATCH[0], BATCH[6], BATCH[1]])
    out = generate_ideas(llm, plan, AutopilotPolicy(), count=3, queue=q)
    assert [e["spec"]["topic"] for e in out["added"]] == [BATCH[1]["topic"]]
    assert BATCH[0]["topic"] in llm.prompts[0] and BATCH[6]["topic"] in llm.prompts[0]


def test_angle_variety_is_enforced(tmp_path):
    same = [idea(t, "emotional") for t in ("Malam pertama Ramadan tanpa keluargaku di Indonesia",
                                           "Saat suamiku belajar bahasa Jawa demi ibuku",
                                           "Telepon dari Lahore yang membuatku menangis",
                                           "Kenapa aku takut pulang kampung setelah menikah")]
    out = generate_ideas(FakeLLM(same), tmp_path / "p.json", AutopilotPolicy(), count=4)
    assert len(out["added"]) == 2 and "too many emotional" in json.dumps(out["rejected"])


def test_duplicate_detection():
    assert is_duplicate("Reaksi keluargaku!", ["reaksi keluargaku"])
    assert not is_duplicate("Pertama kali ke Lahore", ["Reaksi keluargaku waktu aku menikah"])


class _Stub(BaseHTTPRequestHandler):
    reply = ""
    hits = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        type(self).hits.append((self.server.server_port, self.headers.get("authorization"), body["model"]))
        data = json.dumps({"choices": [{"message": {"role": "assistant", "content": type(self).reply}}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture
def stub():
    _Stub.hits = []
    _Stub.reply = json.dumps({"ideas": BATCH[:2]})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()


def test_headroom_used_first_then_falls_back(stub, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OMNIROUTE_API_KEY", "k")
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://127.0.0.1:1/v1")  # direct route is down
    monkeypatch.setenv("HEADROOM_BASE_URL", f"http://127.0.0.1:{stub}/v1")
    p = provider_from_env()
    assert isinstance(p, FallbackProvider) and p.name.startswith("headroom:")
    assert "ideas" in p.complete("x") and _Stub.hits[-1][0] == stub
    monkeypatch.setenv("OMNIROUTE_BASE_URL", f"http://127.0.0.1:{stub}/v1")
    monkeypatch.setenv("HEADROOM_BASE_URL", "http://127.0.0.1:1/v1")  # Headroom is down
    assert "ideas" in provider_from_env().complete("x") and _Stub.hits[-1][1] == "Bearer k"


def test_no_headroom_means_plain_provider(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HEADROOM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OMNIROUTE_API_KEY", "k")
    assert isinstance(provider_from_env(), OpenAICompatibleProvider)


def test_cli_ideas_and_approve(stub, tmp_path):
    env = {**os.environ, "NO_PROXY": "127.0.0.1", "OMNIROUTE_API_KEY": "k", "OMNIROUTE_MODEL": "cc/claude-opus-5-5",
           "OMNIROUTE_BASE_URL": f"http://127.0.0.1:{stub}/v1"}
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HEADROOM_BASE_URL"):
        env.pop(k, None)
    plan, db = str(tmp_path / "plan.json"), str(tmp_path / "jobs.db")
    run = lambda *a: subprocess.run([sys.executable, "-m", "apex.cli", *a], cwd=APEX_ROOT, env=env,
                                    capture_output=True, text=True)
    r = run("ideas", "--plan", plan, "--db", db, "--count", "2")
    assert r.returncode == 0, r.stderr
    added = json.loads(r.stdout)["added"]
    assert len(added) == 2 and _Stub.hits[-1][2] == "cc/claude-opus-5-5"
    assert run("approve", "--plan", plan, "--id", added[0]["id"]).returncode == 0
    assert run("approve", "--plan", plan, "--id", "nope").returncode == 1
    r = run("plan", "--plan", plan, "--db", db)
    decisions = {d["id"]: d["decision"] for d in json.loads(r.stdout)}
    assert decisions == {added[0]["id"]: "ENQUEUED", added[1]["id"]: "WAITING_FOR_APPROVAL"}
