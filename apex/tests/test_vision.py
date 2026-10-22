"""Vision-model creative review: request shape, verdict computed locally, results written back."""
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from apex.script_engine import ProviderUnavailable
from apex.vision import VisionReply, VisionReviewer, review_project, reviewer_from_env, verdict

APEX_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = APEX_ROOT / "samples" / "money-mistake" / "output"


def _png(path: Path, rgb=(30, 120, 200)):
    raw = b"".join(b"\x00" + bytes(rgb) * 4 for _ in range(4))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    (p / "qa" / "frames").mkdir(parents=True)
    shutil.copy(SAMPLE / "storyboard.json", p / "storyboard.json")
    shutil.copy(SAMPLE / "manifest.json", p / "manifest.json")
    qa = json.loads((SAMPLE / "qa_report.json").read_text())
    for f in qa["sampled_frames"]:  # recorded relative to where the pipeline ran
        _png(p / "qa" / "frames" / Path(f).name)
    (p / "qa" / "qa_report.json").write_text(json.dumps(qa))
    return p, len(qa["sampled_frames"])


class _Stub(BaseHTTPRequestHandler):
    reply = {}
    requests = []

    def do_POST(self):  # noqa: N802
        type(self).requests.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
        data = json.dumps({"choices": [{"message": {"content": "```json\n" + json.dumps(type(self).reply) + "\n```"}}]})
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    _Stub.requests = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def frames(n, score=8, over=None):
    over = over or {}
    return {"frames": [{"index": i, "score": over.get(i, score), "matches_scene": True, "issues": []}
                       for i in range(n)], "summary": "ok"}


def test_review_sends_every_frame_with_scene_context_and_writes_back(project, stub):
    p, n = project
    _Stub.reply = frames(n)
    review = review_project(p, VisionReviewer(["http://127.0.0.1:1/v1", stub], "k", "vision-model"))
    assert review["status"] == "PASS" and review["overall_score"] == 8
    content = _Stub.requests[0]["messages"][0]["content"]
    images = [c for c in content if c["type"] == "image_url"]
    assert len(images) == n and images[0]["image_url"]["url"].startswith("data:image/png;base64,iVBOR")
    board = json.loads((p / "storyboard.json").read_text())
    assert board["scenes"][0]["narration_text"] in content[0]["text"]
    assert json.loads((p / "qa" / "qa_report.json").read_text())["creative_review"]["status"] == "PASS"
    manifest = json.loads((p / "manifest.json").read_text())
    assert manifest["qa"]["creative_review"]["overall_score"] == 8 and manifest["qa"]["passed"] is True


def test_verdict_is_computed_not_trusted():
    assert verdict(VisionReply.model_validate(frames(4, 9, {2: 4})), 4)["status"] == "NEEDS_WORK"  # one weak frame
    assert verdict(VisionReply.model_validate(frames(4, 6)), 4)["status"] == "NEEDS_WORK"  # mediocre overall
    assert "no review for frames [3]" in verdict(VisionReply.model_validate(frames(3, 9)), 4)["reasons"]
    bad = frames(2, 9)
    bad["frames"][1]["matches_scene"] = False
    assert verdict(VisionReply.model_validate(bad), 2)["status"] == "NEEDS_WORK"


def test_reply_without_scores_is_rejected(project, stub):
    p, _ = project
    _Stub.reply = {"verdict": "PASS", "summary": "Looks great!"}
    with pytest.raises(Exception):
        review_project(p, VisionReviewer([stub], "k", "m"))
    assert json.loads((p / "qa" / "qa_report.json").read_text())["creative_review"]["status"] == "NOT RUN"


def test_reviewer_needs_credentials_and_prefers_headroom(monkeypatch):
    for k in ("OMNIROUTE_API_KEY", "OPENAI_API_KEY", "HEADROOM_BASE_URL", "APEX_VISION_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ProviderUnavailable):
        reviewer_from_env()
    monkeypatch.setenv("OMNIROUTE_API_KEY", "k")
    monkeypatch.setenv("HEADROOM_BASE_URL", "http://127.0.0.1:8765/v1")
    monkeypatch.setenv("APEX_VISION_MODEL", "cc/claude-opus-5-5")
    r = reviewer_from_env()
    assert r.base_urls == ["http://127.0.0.1:8765/v1", "http://127.0.0.1:20128/v1"] and r.model == "cc/claude-opus-5-5"


def test_cli_review(project, stub):
    p, n = project
    _Stub.reply = frames(n, 9, {0: 3})
    env = {**os.environ, "NO_PROXY": "127.0.0.1", "OMNIROUTE_API_KEY": "k", "OMNIROUTE_BASE_URL": stub}
    env.pop("HEADROOM_BASE_URL", None)
    r = subprocess.run([sys.executable, "-m", "apex.cli", "review", "--project", str(p)], cwd=APEX_ROOT, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "NEEDS_WORK" and "frames below 5.0: [0]" in out["reasons"]
