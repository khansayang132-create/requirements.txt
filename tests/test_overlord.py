"""OVERLORD: production tools, the agent registry and the self-healing engine, against real programs where cheap."""
import json
import os
import shutil
import subprocess
import time

import pytest
from test_agency import make, repo, run_playbook  # noqa: F401  (repo is a fixture)

from agency import departments, production
from agency import orchestrator as orch
from agency.healing import MAX_HEALS, Healer, classify
from agency.orchestrator import Step
from agency.store import Store
from agency.tools import Tool, ToolResult
from agency.worker import Worker

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


def flaky(tb, results):
    """Replace py_compile with a scripted tool so the orchestrator and healer meet real ERROR / FAIL / BLOCKED."""
    seq = list(results)

    def fn(paths):
        status, summary = seq.pop(0) if len(seq) > 1 else seq[0]
        return ToolResult(status, summary, exit_code=0 if status == "PASS" else 1)
    old = tb.tools["py_compile"]
    tb.tools["py_compile"] = Tool(old.name, old.description, old.params, old.permission, old.timeout, False, fn)


def clocked(repo):
    clock = Clock()
    store, tb = make(repo)
    return Store(repo / "heal.db", clock=clock), tb, clock


# ---------------------------------------------------------------- classifier
@pytest.mark.parametrize("status, summary, category", [
    ("ERROR", "timed out after 60s", "transient"),
    ("BLOCKED", "codex is not installed", "missing_dependency"),
    ("BLOCKED", "piper-tts installed, but no voice model is installed", "missing_dependency"),
    ("BLOCKED", "elevenlabs: no credential in the environment (ELEVENLABS_API_KEY)", "credential"),
    ("BLOCKED", "codex 0.1 installed, not logged in", "credential"),
    ("BLOCKED", "dependency did not pass: build FAILED", "dependency"),
    ("FAIL", "3 tests failed", "check_failed"),
    ("FAIL", "render timed out in a test", "check_failed"),   # a FAIL verdict is never treated as transient
    ("BLOCKED", "something odd", "unknown"),
])
def test_classifier(status, summary, category):
    assert classify(status, summary) == category


# ---------------------------------------------------------------- self-healing
def test_transient_failure_is_retried_with_backoff_and_completes(repo, monkeypatch):
    store, tb, clock = clocked(repo)
    flaky(tb, [("ERROR", "timed out after 60s"), ("ERROR", "timed out after 60s"), ("PASS", "ok")])
    mid, state = run_playbook(monkeypatch, store, tb, [Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]})])
    assert state == "FAILED"                                   # the orchestrator's own 2 attempts both errored
    h = Healer(store)
    assert h.heal()["actions"] == {f"{mid}.a": "scheduled"}
    assert h.heal()["actions"] == {f"{mid}.a": "backing off"}  # before the backoff expires nothing happens
    clock.t += 61
    assert h.heal()["actions"] == {f"{mid}.a": "retried"}
    assert store.mission(mid)["state"] == "READY"
    assert orch.Orchestrator(store, tb).run(mid) == "COMPLETED"
    assert [r["action"] for r in h.history(f"{mid}.a")] == ["scheduled", "retry"]


def test_retries_are_bounded_then_escalated(repo, monkeypatch):
    store, tb, clock = clocked(repo)
    flaky(tb, [("ERROR", "connection reset")])
    mid, _ = run_playbook(monkeypatch, store, tb, [Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]})])
    h = Healer(store)
    for _ in range(20):                                        # many passes, far beyond the limit: no infinite loop
        h.heal()
        clock.t += 10_000
        if store.mission(mid)["state"] == "READY":
            orch.Orchestrator(store, tb).run(mid)
    actions = [r["action"] for r in h.history(f"{mid}.a")]
    assert actions.count("retry") == MAX_HEALS and actions[-1] == "gave_up" and actions.count("gave_up") == 1
    assert store.task(f"{mid}.a")["state"] == "FAILED"         # not discarded: still visible as FAILED


def test_real_failures_and_credentials_escalate_once_and_never_retry(repo, monkeypatch):
    store, tb, clock = clocked(repo)
    flaky(tb, [("FAIL", "3 tests failed")])
    m1, _ = run_playbook(monkeypatch, store, tb, [Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]})])
    flaky(tb, [("BLOCKED", "heygen: no credential in the environment (HEYGEN_API_KEY)")])
    m2, _ = run_playbook(monkeypatch, store, tb, [Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]})])
    h = Healer(store)
    for _ in range(3):
        rep = h.heal()
        clock.t += 10_000
    assert rep["actions"] == {f"{m1}.a": "escalated", f"{m2}.a": "escalated"}
    for mid, cat in ((m1, "check_failed"), (m2, "credential")):
        rows = h.history(f"{mid}.a")
        assert [(r["category"], r["action"]) for r in rows] == [(cat, "escalated")]
    assert store.mission(m1)["state"] == "FAILED" and store.mission(m2)["state"] == "BLOCKED"


def test_dependants_come_back_with_their_upstream(repo, monkeypatch):
    store, tb, clock = clocked(repo)
    flaky(tb, [("BLOCKED", "codex is not installed"), ("PASS", "ok")])
    mid, state = run_playbook(monkeypatch, store, tb, [
        Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]}),
        Step("b", "b", "code_review", "git_diff", after=("a",))])
    assert state == "BLOCKED" and store.task(f"{mid}.b")["state"] == "BLOCKED"
    h = Healer(store)
    h.heal()
    clock.t += 601
    assert h.heal()["actions"][f"{mid}.a"] == "retried"        # e.g. the program got installed meanwhile
    assert store.task(f"{mid}.b")["state"] == "READY"
    assert orch.Orchestrator(store, tb).run(mid) == "COMPLETED"


def test_watchdog_requeues_a_dead_runners_task_and_logs_it(repo, monkeypatch):
    store, tb, clock = clocked(repo)
    monkeypatch.setitem(orch.PLAYBOOKS, "t", orch.Playbook("t", (Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]}),)))
    mid = orch.plan(store, tb, "t")
    store.move_mission(mid, orch.State.RUNNING, "runner")
    store.move_task(f"{mid}.a", orch.State.RUNNING, "runner", lease_owner="dead", lease_expires_at=clock.t - 1)
    h = Healer(store)
    assert h.heal()["requeued"] == [f"{mid}.a"]
    assert store.task(f"{mid}.a")["state"] == "READY"
    assert h.history(f"{mid}.a")[0]["action"] == "requeued"


def test_stalled_worker_and_recurring_failures_are_reported(repo, monkeypatch):
    store, tb, clock = clocked(repo)
    store.heartbeat("old-worker")
    clock.t += 3600
    flaky(tb, [("FAIL", "render broke")])
    for _ in range(3):
        run_playbook(monkeypatch, store, tb, [Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]})])
    h = Healer(store)
    rep = h.heal()
    assert rep["stalled_workers"] == [{"worker": "old-worker", "age_s": 3600}]
    assert rep["recurring"] == [{"step": "t.a", "missions": 3}]
    h.heal()
    assert len([r for r in h.recent() if r["category"] == "recurring"]) == 1   # escalated once, not every pass


def test_worker_heals_then_resumes_without_a_human(repo, monkeypatch):
    store, tb, clock = clocked(repo)
    flaky(tb, [("ERROR", "timed out"), ("ERROR", "timed out"), ("PASS", "ok")])
    mid, _ = run_playbook(monkeypatch, store, tb, [Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]})])
    wk = Worker(store, tb, None, 3600, idle=0)
    wk.tick()                                                  # schedules the retry
    clock.t += 61
    ran = wk.tick()                                            # retries, then resumes the mission itself
    assert (mid, "COMPLETED") in ran


# ---------------------------------------------------------------- production tools
def _clip(path, audio=True, seconds=1):
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=64x64:rate=12:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=d={seconds}", "-c:a", "aac", "-shortest"]
    subprocess.run([*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


@needs_ffmpeg
def test_media_verify_checks_streams_duration_and_decoding(repo):
    _, tb = make(repo)
    _clip(repo / "av.mp4")
    _clip(repo / "silent.mp4", audio=False)
    (repo / "empty.mp4").write_bytes(b"")
    (repo / "junk.mp4").write_bytes(b"not a video" * 100)
    mv = tb.tools["media_verify"].fn
    ok = mv("av.mp4")
    assert ok.status == "PASS" and ok.evidence["streams"] == ["video", "audio"] and ok.evidence["duration_s"] >= 0.9
    assert mv("silent.mp4").status == "FAIL" and "no audio" in mv("silent.mp4").summary
    assert mv("silent.mp4", need_audio=False).status == "PASS"
    assert mv("empty.mp4").status == "FAIL" and mv("junk.mp4").status == "FAIL"


@needs_ffmpeg
def test_verifier_reprobes_media_instead_of_trusting_the_claim(repo):
    _, tb = make(repo)
    _clip(repo / "out.mp4")
    call = {"status": "PASS", "evidence": json.dumps({"media": str(repo / "out.mp4"), "streams": ["video", "audio"]})}
    assert production.recheck(None, call, tb)[0] is True
    (repo / "out.mp4").unlink()                                # the file disappears after the runner claimed PASS
    ok, note = production.recheck(None, call, tb)
    assert ok is False and "missing" in note


@needs_ffmpeg
def test_integration_audit_runs_through_the_orchestrator(repo, monkeypatch):
    store, tb = make(repo, env={"PATH": "/usr/bin:/bin"})
    mid, _ = run_playbook(monkeypatch, store, tb, [
        Step("ffmpeg", "ffmpeg", "technical", "integration_probe", {"name": "ffmpeg"}),
        Step("eleven", "eleven", "technical", "integration_probe", {"name": "elevenlabs"}),
        Step("comfy", "comfy", "technical", "integration_probe", {"name": "comfyui"})])
    s = {t["step"]: t for t in store.tasks(mid)}
    assert s["ffmpeg"]["state"] == "COMPLETED"
    assert s["eleven"]["state"] == "BLOCKED" and "no credential" in s["eleven"]["summary"]
    assert s["comfy"]["state"] == "BLOCKED"
    ev = {c["task_id"].split(".")[-1]: json.loads(c["evidence"])["integration_status"] for c in store.calls(mid)}
    assert ev["ffmpeg"] == "VERIFIED" and ev["eleven"] == "BLOCKED" and ev["comfy"] == "NOT INSTALLED"


def test_production_tools_report_blocked_without_their_environment(repo):
    _, tb = make(repo)
    assert tb.tools["build_character"].fn("CHAR-HUM-001", "x").status == "BLOCKED"
    assert tb.tools["voice_dialogue"].fn("ok.py", "x").status == "BLOCKED"
    assert tb.tools["project_tests"].fn("auravox").status == "BLOCKED"
    assert tb.tools["integration_probe"].fn("blender").evidence["integration_status"] == "NOT INSTALLED"


def test_every_registered_agent_runs_a_tool_its_role_may_call():
    assert departments.check() == []
    named = {a.name for a in departments.AGENTS}
    assert len(named) == len(departments.AGENTS) == 37
    implemented = [a for a in departments.AGENTS if a.tool]
    assert len(implemented) >= 25


def test_an_asset_being_written_by_another_agent_is_not_overwritten(repo):
    _, tb = make(repo)
    d = repo / production.OUT / "dh-x"
    d.mkdir(parents=True)
    (d / ".scene.lock").write_text(str(os.getpid()))       # a live writer (this process) holds the scene
    r = tb.tools["talking_scene"].fn("p", "dh-x")
    assert r.status == "BLOCKED" and "not overwriting" in r.summary
    (d / ".scene.lock").write_text("999999999")            # its writer died: the lock is stale and taken over
    r = tb.tools["talking_scene"].fn("p", "dh-x")
    assert "not overwriting" not in r.summary and not (d / ".scene.lock").exists()


def test_secret_scan_skips_sk_test_fixtures_but_not_real_looking_keys(repo):
    """Root cause of the failing nightly health run on main: fake keys in tests were reported as credentials."""
    _, tb = make(repo)
    fixture = "sk-test-" + "omniroute-key-0123456789abcdef"
    real_looking = "sk-" + "proj" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    (repo / "t.sh").write_text(f"KEY={fixture}\n")
    (repo / "u.py").write_text(f"k = '{fixture}' or '{real_looking}'\n")   # a real-looking key on the same line still counts
    subprocess.run(["git", "-C", str(repo), "add", "t.sh", "u.py"], check=True)
    r = tb.tools["secret_scan"].fn()
    assert r.status == "FAIL" and "u.py:1" in r.output and "t.sh" not in r.output


@needs_ffmpeg
def test_media_verify_reports_black_and_silent_media(repo):
    _, tb = make(repo)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:size=64x64:rate=12:d=3",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(repo / "dead.mp4")], check=True)
    r = tb.tools["media_verify"].fn("dead.mp4")
    assert r.status == "FAIL" and "black throughout" in r.summary and "silent throughout" in r.summary
    _clip(repo / "ok.mp4", seconds=3)
    ok = tb.tools["media_verify"].fn("ok.mp4")
    assert ok.status == "PASS" and ok.evidence["black_s"] == 0 and ok.evidence["silent_s"] == 0


def test_worker_finishes_a_job_then_claims_the_next_eligible_one(repo, monkeypatch):
    """Skill definition of done: a verified job completes and the worker proceeds to the next one."""
    store, tb = make(repo)
    monkeypatch.setitem(orch.PLAYBOOKS, "t", orch.Playbook("t", (Step("a", "a", "qa", "py_compile", {"paths": ["ok.py"]}),)))
    first, second = orch.plan(store, tb, "t"), orch.plan(store, tb, "t")
    ran = Worker(store, tb, None, 3600, idle=0).tick()
    assert ran == [(first, "COMPLETED"), (second, "COMPLETED")]
    assert Worker(store, tb, None, 3600, idle=0).tick() == []    # nothing left: no duplicate processing
