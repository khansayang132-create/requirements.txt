"""Autopilot policy, content planner, emergency stop, and the read-only dashboard."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from apex.autopilot import AutopilotPolicy, load_policy, run_plan, save_policy, topic_violations
from apex.jobs import JobQueue
from apex.models import JobState, ProductionSpec

APEX_ROOT = Path(__file__).resolve().parent.parent
SPEC = {"topic": "Kebiasaan kecil yang menguras gaji", "language": "id", "target_seconds": 30}


def entry(eid, approved=True, **spec_overrides):
    return {"id": eid, "approved": approved, "spec": {**SPEC, **spec_overrides}}


def test_missing_policy_file_means_safe_defaults(tmp_path):
    p = load_policy(tmp_path / "none.json")
    assert p.require_approval and not p.paused and p.max_jobs_per_day == 3


def test_policy_roundtrip(tmp_path):
    save_policy(AutopilotPolicy(paused=True, max_jobs_per_day=5), tmp_path / "a.json")
    assert load_policy(tmp_path / "a.json").paused


def test_topic_rules():
    spec = ProductionSpec.model_validate(SPEC)
    assert topic_violations(AutopilotPolicy(prohibited_topics=["gaji"]), spec)
    assert topic_violations(AutopilotPolicy(allowed_topics=["nikah"]), spec)
    assert topic_violations(AutopilotPolicy(allowed_topics=["GAJI"]), spec) == []


def test_plan_enforces_approval_topics_limit_and_idempotency(tmp_path):
    q = JobQueue(tmp_path / "jobs.db")
    policy = AutopilotPolicy(max_jobs_per_day=2, prohibited_topics=["judi"])
    plan = [entry("a"), entry("b", approved=False), entry("c", topic="Tips judi online"),
            entry("d"), entry("e"), {"id": "f", "approved": True, "spec": {"topic": "x"}}]
    d = {x["id"]: x["decision"] for x in run_plan(plan, q, policy, tmp_path)}
    assert d == {"a": "ENQUEUED", "b": "WAITING_FOR_APPROVAL", "c": "REJECTED", "d": "ENQUEUED",
                 "e": "DEFERRED", "f": "REJECTED"}
    assert q.counts() == {"QUEUED": 2}
    again = {x["id"]: x["decision"] for x in run_plan(plan, q, policy, tmp_path)}
    assert again["a"] == "EXISTS" and again["d"] == "EXISTS" and again["e"] == "DEFERRED"
    assert q.counts() == {"QUEUED": 2}


def test_plan_spec_from_file(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps(SPEC))
    q = JobQueue(tmp_path / "jobs.db")
    out = run_plan([{"id": "x", "approved": True, "spec": "s.json"}], q, AutopilotPolicy(), tmp_path)
    assert out[0]["decision"] == "ENQUEUED"
    assert q.get(out[0]["job_id"]).payload["project"] == str((tmp_path / "out" / "x").resolve())


def test_paused_plan_enqueues_nothing(tmp_path):
    q = JobQueue(tmp_path / "jobs.db")
    out = run_plan([entry("a")], q, AutopilotPolicy(paused=True), tmp_path)
    assert out[0]["decision"] == "SKIPPED" and q.counts() == {}


def test_worker_takes_no_jobs_while_paused(tmp_path):
    db = tmp_path / "jobs.db"
    q = JobQueue(db)
    job = q.enqueue("k", "produce_video", {"spec": SPEC, "project": str(tmp_path / "p")})
    save_policy(AutopilotPolicy(paused=True), tmp_path / "autopilot.json")
    p = subprocess.Popen([sys.executable, "-u", "-m", "apex.cli", "worker", "--db", str(db), "--poll", "0.2"],
                         cwd=APEX_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(3)
        assert q.get(job.id).state == JobState.QUEUED
    finally:
        p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=20)
    assert "autopilot paused" in out and "worker stopped" in out


def test_cli_stop_and_resume(tmp_path):
    db = str(tmp_path / "jobs.db")
    run = lambda *args: subprocess.run([sys.executable, "-m", "apex.cli", *args, "--db", db], cwd=APEX_ROOT,
                                       capture_output=True, text=True, check=True)
    run("stop")
    assert load_policy(tmp_path / "autopilot.json").paused
    run("resume")
    assert not load_policy(tmp_path / "autopilot.json").paused
    run("policy", "--max-per-day", "7", "--prohibit", "judi,pinjol")
    pol = load_policy(tmp_path / "autopilot.json")
    assert pol.max_jobs_per_day == 7 and pol.prohibited_topics == ["judi", "pinjol"]


@pytest.fixture
def dashboard(tmp_path):
    from apex.dashboard import serve
    q = JobQueue(tmp_path / "jobs.db")
    done = q.enqueue("done", "produce_video", {"spec": SPEC, "project": str(tmp_path)})
    q.claim("w")
    video = tmp_path / "final.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
    q.complete(done.id, {"final": {"path": str(video), "sha256": "abc"}, "qa": {"passed": True, "technical_score": 1.0,
                                                                              "creative_review": {"status": "NOT RUN"}}})
    other = q.enqueue("other", "produce_video", {"spec": SPEC, "project": str(tmp_path)})
    srv = serve(tmp_path / "jobs.db", tmp_path / "autopilot.json", port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", done.id, other.id
    srv.shutdown()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_dashboard_pages(dashboard, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    base, done, other = dashboard
    code, body = _get(base + "/")
    assert code == 200 and done.encode() in body and b"COMPLETED" in body and b"Jobs today" in body
    code, body = _get(f"{base}/job/{done}")
    assert code == 200 and b"QUALITY_REVIEW" in body and b"<video" in body and b"PASS" in body
    code, body = _get(f"{base}/media/{done}")
    assert code == 200 and body.startswith(b"\x00\x00\x00\x18ftyp")
    assert json.loads(_get(base + "/health")[1])["counts"] == {"COMPLETED": 1, "QUEUED": 1}


def test_dashboard_never_serves_arbitrary_paths(dashboard, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    base, done, other = dashboard
    assert _get(f"{base}/media/{other}")[0] == 404          # job without a finished video
    assert _get(f"{base}/media/../../etc/passwd")[0] == 404
    assert _get(f"{base}/job/nonexistent")[0] == 404
    assert _get(f"{base}/job/{'0' * 12}")[0] == 404


def _get_range(url, rng):
    req = urllib.request.Request(url, headers={"Range": rng})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_dashboard_video_supports_byte_ranges(dashboard, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    base, done, _ = dashboard
    full = b"\x00\x00\x00\x18ftypmp42fake"
    code, headers, body = _get_range(f"{base}/media/{done}", "bytes=0-3")
    assert code == 206 and body == full[:4] and headers["content-range"] == f"bytes 0-3/{len(full)}"
    code, _, body = _get_range(f"{base}/media/{done}", "bytes=-4")
    assert code == 206 and body == full[-4:]
    code, _, body = _get_range(f"{base}/media/{done}", "bytes=4-")
    assert code == 206 and body == full[4:]
    assert _get_range(f"{base}/media/{done}", "bytes=999-")[0] == 416
