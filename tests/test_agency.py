"""Engineering agency: planning rules, permissions, failure reporting, retries, recovery, approval, redaction."""
import dataclasses
import json
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agency import orchestrator as orch  # noqa: E402
from agency.dashboard import serve  # noqa: E402
from agency.providers import OpenAICompatible  # noqa: E402
from agency.report import markdown  # noqa: E402
from agency.roles import ROLES, VERIFIER  # noqa: E402
from agency.store import InvalidTransition, State, Store  # noqa: E402
from agency.tools import (  # noqa: E402
    ApprovalRequired,
    InvalidInput,
    PermissionDenied,
    Toolbox,
    ToolResult,
    redact,
)

Step, Playbook = orch.Step, orch.Playbook
FAKE_KEY = "sk-" + "a1B2" * 8  # built at runtime so the repo's own secret scan stays clean


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / "t_ok").mkdir()
    (tmp_path / "t_ok" / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    (tmp_path / "t_bad").mkdir()
    (tmp_path / "t_bad" / "test_bad.py").write_text("def test_bad():\n    assert 1 + 1 == 3\n")
    (tmp_path / "ok.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
                   check=True)
    return tmp_path


def make(repo, env=None, provider_factory=None, config=None):
    kwargs = {"provider_factory": provider_factory} if provider_factory else {}
    tb = Toolbox(repo, suites={"ok": (".", ["t_ok"]), "bad": (".", ["t_bad"])}, env=env or {"PATH": "/usr/bin:/bin"},
                 config=config or {}, **kwargs)
    return Store(repo / "agency.db"), tb


def run_playbook(monkeypatch, store, tb, steps, **plan_kwargs):
    monkeypatch.setitem(orch.PLAYBOOKS, "t", Playbook("test", tuple(steps)))
    mid = orch.plan(store, tb, "t", **plan_kwargs)
    return mid, orch.Orchestrator(store, tb, concurrency=3).run(mid)


def states(store, mid):
    return {t["step"]: t["state"] for t in store.tasks(mid)}


# --------------------------------------------------------------------------- registry and planning
def test_roles_are_distinct_and_tools_exist(repo):
    _, tb = make(repo)
    assert len(ROLES) == 20
    assert len({r.tools for r in ROLES.values()}) > 5  # permissions actually differ between roles
    for role in ROLES.values():
        assert role.tools <= set(tb.tools), role.id
        assert VERIFIER[role.id] != role.id


def test_shipped_playbooks_are_valid(repo):
    tb = Toolbox(Path(__file__).resolve().parents[1])
    params = {"request": "x", "paths": "bot.py", "branch": "b", "patch": "x", "role": "fullstack",
              "package": "pytest", "server": "headroom"}
    for name in orch.playbook_names():
        pb = orch.PLAYBOOKS.get(name) or orch.dynamic_playbook(name, tb)
        orch.validate_playbook(orch.with_params(pb, params, tb), tb)


@pytest.mark.parametrize("steps, message", [
    ([Step("a", "", "qa", "secret_scan")], "not permitted"),
    ([Step("a", "", "qa", "no_such_tool")], "unknown tool"),
    ([Step("a", "", "nobody", "git_status")], "unknown role"),
    ([Step("a", "", "qa", "git_status", after=("b",)), Step("b", "", "qa", "git_status", after=("a",))], "cycle"),
    ([Step("a", "", "qa", "git_status", after=("zz",))], "unknown step"),
    ([Step("a", "", "qa", "run_tests", {"suite": "nope"})], "must be one of"),
    ([Step("d", "", "code_review", "git_diff"), Step("r", "", "ai_engineer", "llm_review", handoff={"diff": ("d", "diff")})],
     "not a dependency"),
])
def test_plan_rejects_bad_playbooks(repo, monkeypatch, steps, message):
    store, tb = make(repo)
    monkeypatch.setitem(orch.PLAYBOOKS, "t", Playbook("test", tuple(steps)))
    with pytest.raises(orch.PlanError, match=message):
        orch.plan(store, tb, "t")
    assert store.missions()[0]["state"] == "FAILED"  # the rejection is recorded, nothing ran
    assert store.calls(store.missions()[0]["id"]) == []


def test_invalid_transition_is_refused(repo):
    store, _ = make(repo)
    mid = store.create_mission("x", "x", 5)
    with pytest.raises(InvalidTransition):
        store.move_mission(mid, State.COMPLETED)


# --------------------------------------------------------------------------- tool policy
def test_tool_permissions_and_input_boundaries(repo):
    _, tb = make(repo)
    (repo / ".env").write_text(f"OPENAI_API_KEY={FAKE_KEY}\n")
    with pytest.raises(PermissionDenied):
        tb.call(ROLES["qa"], "secret_scan", {})
    with pytest.raises(InvalidInput, match="not readable"):
        tb.call(ROLES["qa"], "read_file", {"path": ".env"})
    with pytest.raises(InvalidInput, match="outside"):
        tb.call(ROLES["qa"], "read_file", {"path": "../../etc/passwd"})
    with pytest.raises(InvalidInput, match="disallowed"):
        tb.call(ROLES["devops"], "py_compile", {"paths": ["ok.py; rm -rf /"]})
    with pytest.raises(InvalidInput, match="unknown argument"):
        tb.call(ROLES["qa"], "git_status", {"cmd": "ls"})
    with pytest.raises(ApprovalRequired):
        tb.call(ROLES["ai_engineer"], "llm_review", {"diff": "x"})
    assert tb.call(ROLES["qa"], "read_file", {"path": "ok.py"}).status == "PASS"


def test_missing_program_is_blocked_not_passed(repo):
    _, tb = make(repo, env={"PATH": str(repo)})  # nothing installed on this PATH
    tb.tools["ruff"] = dataclasses.replace(tb.tools["ruff"], fn=lambda paths: tb._linter(["no-such-linter-xyz"], "x"))
    assert tb.call(ROLES["code_review"], "ruff", {"paths": ["ok.py"]}).status == "BLOCKED"


def test_output_is_redacted_and_child_env_has_no_secrets(repo):
    env = {"PATH": "/usr/bin:/bin", "OMNIROUTE_API_KEY": "plain-secret-value-123"}
    _, tb = make(repo, env=env)
    (repo / "leak.py").write_text(f"KEY = '{FAKE_KEY}'\nprint('plain-secret-value-123')\n")
    out = tb.call(ROLES["qa"], "read_file", {"path": "leak.py"}).output
    assert FAKE_KEY not in out and "plain-secret-value-123" not in out and "[REDACTED" in out
    assert "OMNIROUTE_API_KEY" not in tb._child_env()
    assert redact("token 1234567890:" + "A" * 35) == "token [REDACTED:telegram-token]"


def test_secret_scan_finds_tracked_credentials(repo):
    _, tb = make(repo)
    assert tb.call(ROLES["security"], "secret_scan", {}).status == "PASS"
    (repo / "config.py").write_text(f"api_key = '{FAKE_KEY}'\n")
    subprocess.run(["git", "-C", str(repo), "add", "config.py"], check=True)
    r = tb.call(ROLES["security"], "secret_scan", {})
    assert r.status == "FAIL" and "config.py:1" in r.output and FAKE_KEY not in r.output


# --------------------------------------------------------------------------- execution
def test_passing_and_intentionally_failing_tests_are_reported_honestly(repo, monkeypatch):
    store, tb = make(repo)
    mid, final = run_playbook(monkeypatch, store, tb, [
        Step("good", "", "qa", "run_tests", {"suite": "ok"}),
        Step("bad", "", "qa", "run_tests", {"suite": "bad"}),
        Step("after-bad", "", "devops", "git_status", after=("bad",)),
        Step("compile", "", "devops", "py_compile", {"paths": ["ok.py"]}),
    ])
    assert final == "FAILED"
    assert states(store, mid) == {"good": "COMPLETED", "bad": "FAILED", "after-bad": "BLOCKED", "compile": "COMPLETED"}
    bad = store.task(f"{mid}.bad")
    assert bad["attempts"] == 1  # a deterministic failure is not retried
    assert "1 failed" in bad["summary"] and "confirmed the failure" in store.events(bad["id"])[-1]["detail"]
    assert "code_review" == bad["verifier"]
    report = markdown(store, mid)
    assert "| bad | qa → code_review | `run_tests` | **FAIL**" in report
    assert "| after-bad |" in report and "**BLOCKED**" in report and "dependency did not pass: bad FAILED" in report
    trail = [(e["from_state"], e["to_state"]) for e in store.events(f"{mid}.good")]
    assert trail == [(None, "PLANNED"), ("PLANNED", "READY"), ("READY", "RUNNING"), ("RUNNING", "REVIEWING"),
                     ("REVIEWING", "VERIFYING"), ("VERIFYING", "COMPLETED")]


def test_errors_retry_a_bounded_number_of_times(repo, monkeypatch):
    store, tb = make(repo)
    calls = []

    def always_times_out():
        calls.append(1)
        return ToolResult("ERROR", "timed out after 15s")
    tb.tools["git_status"] = dataclasses.replace(tb.tools["git_status"], fn=always_times_out)
    mid, final = run_playbook(monkeypatch, store, tb, [Step("s", "", "devops", "git_status")], max_attempts=3)
    assert final == "FAILED" and len(calls) == 3
    assert store.task(f"{mid}.s")["attempts"] == 3 and len(store.calls(mid)) == 3
    assert orch.Orchestrator(store, tb).run(mid) == "FAILED" and len(calls) == 3  # resume doesn't loop


def test_tool_call_budget_blocks_the_rest(repo, monkeypatch):
    store, tb = make(repo)
    mid, final = run_playbook(monkeypatch, store, tb, [Step(f"s{i}", "", "devops", "git_status") for i in range(4)],
                              call_budget=2)
    assert final == "BLOCKED" and len(store.calls(mid)) == 2
    assert list(states(store, mid).values()).count("BLOCKED") == 2


def test_restart_recovers_a_task_left_running(repo, monkeypatch):
    store, tb = make(repo)
    monkeypatch.setitem(orch.PLAYBOOKS, "t", Playbook("t", (Step("s", "", "devops", "git_status"),)))
    mid = orch.plan(store, tb, "t")
    store.move_mission(mid, State.RUNNING)
    store.move_task(f"{mid}.s", State.RUNNING, "crashed worker", attempts=1, lease_owner="dead:1", lease_expires_at=0)
    fresh = Store(repo / "agency.db")  # a new process opening the same database
    assert orch.Orchestrator(fresh, tb).run(mid) == "COMPLETED"
    assert any("lease expired" in (e["detail"] or "") for e in fresh.events(f"{mid}.s"))
    assert fresh.task(f"{mid}.s")["attempts"] == 2


def test_cancel_stops_a_mission(repo, monkeypatch):
    store, tb = make(repo)
    monkeypatch.setitem(orch.PLAYBOOKS, "t", Playbook("t", (Step("s", "", "devops", "git_status"),)))
    mid = orch.plan(store, tb, "t")
    orch.cancel(store, mid, "tester")
    assert orch.Orchestrator(store, tb).run(mid) == "CANCELLED"
    assert store.calls(mid) == [] and states(store, mid) == {"s": "CANCELLED"}


def test_evidence_mismatch_is_caught():
    task = {"tool": "run_tests"}
    forged = {"status": "PASS", "exit_code": 1, "output": "1 failed, 3 passed in 0.1s", "evidence": "{}"}
    assert orch.check_evidence(task, forged)[0] is False
    assert orch.check_evidence(task, None)[0] is False
    assert orch.check_evidence(task, {"status": "PASS", "exit_code": 0, "output": "3 passed in 0.1s", "evidence": "{}"})[0] is True


# --------------------------------------------------------------------------- approval and provider
class StubLLM(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StubLLM.seen.append((self.headers["Authorization"], body))
        out = json.dumps({"model": "stub-1", "choices": [{"message": {"content": "No blocking findings."}}],
                          "usage": {"prompt_tokens": 42, "completion_tokens": 4}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def test_review_needs_approval_then_runs_against_provider(repo, monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), StubLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"
    store, tb = make(repo, provider_factory=lambda env: OpenAICompatible(base, "test-key-123456", "stub"))
    (repo / "ok.py").write_text("x = 2\n")
    try:
        mid = orch.plan(store, tb, "review")
        assert orch.Orchestrator(store, tb).run(mid) == "NEEDS_APPROVAL"
        assert StubLLM.seen == []  # nothing left the machine before approval
        orch.approve(store, f"{mid}.llm-review", "owner")
        assert orch.Orchestrator(store, tb).run(mid) == "COMPLETED"
    finally:
        srv.shutdown()
    auth, body = StubLLM.seen[-1]
    assert auth == "Bearer test-key-123456" and "x = 2" in body["messages"][1]["content"]  # handoff carried the diff
    call = store.last_call(f"{mid}.llm-review")
    ev = json.loads(call["evidence"])
    assert ev["prompt_tokens"] == 42 and ev["llm_calls"] == 1 and "No blocking findings." in call["output"]
    assert store.task(f"{mid}.llm-review")["approved_by"] == "owner"


def test_review_without_credentials_is_blocked(repo, monkeypatch):
    store, tb = make(repo)  # default provider_from_env with an env that has no key
    (repo / "ok.py").write_text("x = 3\n")
    mid = orch.plan(store, tb, "review")
    orch.approve(store, f"{mid}.llm-review", "owner")
    assert orch.Orchestrator(store, tb).run(mid) == "BLOCKED"
    assert "no LLM key" in store.task(f"{mid}.llm-review")["summary"]


# --------------------------------------------------------------------------- dashboard
def test_dashboard_shows_real_state_and_escapes_output(repo, monkeypatch):
    store, tb = make(repo)
    (repo / "x.py").write_text("<script>alert(1)</script>\n")
    mid, _ = run_playbook(monkeypatch, store, tb, [Step("read", "", "qa", "read_file", {"path": "x.py"})])
    srv = serve(store, tb, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        home = urllib.request.urlopen(base + "/").read().decode()
        page = urllib.request.urlopen(f"{base}/mission/{mid}").read().decode()
        health = json.load(urllib.request.urlopen(base + "/health"))
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/mission/../etc")
    finally:
        srv.shutdown()
    assert srv.server_address[0] == "127.0.0.1"
    assert mid in home and "idle: no playbook yet" in home and "Senior Backend Engineer" in home
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert" not in page
    assert "COMPLETED" in page and health == {"ok": True, "missions": 1}
