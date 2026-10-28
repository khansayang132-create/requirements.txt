"""Engineering agency, stage 2: code changes on branches, push, planner, cancel-kill, health URLs, MCP,
dashboard actions, worker, usage/cost, schema migration."""
import json
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agency import orchestrator as orch  # noqa: E402
from agency import planner  # noqa: E402
from agency.dashboard import serve  # noqa: E402
from agency.providers import Completion  # noqa: E402
from agency.report import markdown, usage  # noqa: E402
from agency.roles import ROLES  # noqa: E402
from agency.store import State, Store  # noqa: E402
from agency.tools import ApprovalRequired, InvalidInput, PermissionDenied, Toolbox, patch_paths  # noqa: E402
from agency.worker import Worker  # noqa: E402

Step, Playbook = orch.Step, orch.Playbook
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *GIT_ID, *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text(".env\nagency/out/\n*.db*\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n")
    (tmp_path / "README.md").write_text("# Demo\n\nHello.\n")
    (tmp_path / "bot.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path


class FakeProvider:
    """Returns canned replies in order; records prompts. Stands in for an OpenAI-compatible gateway."""

    def __init__(self, *replies, model="stub-1"):
        self.replies, self.model, self.prompts = list(replies), model, []
        self.label = "fake"

    def complete(self, system, user, max_tokens=1200):
        self.prompts.append(user)
        return Completion(self.replies.pop(0), self.model, 100, 20)


def make(repo, provider=None, config=None, suites=None):
    tb = Toolbox(repo, suites=suites or {"bot": (".", ["tests"]), "apex": (".", ["tests"]), "slow": (".", ["slow"])},
                 env={"PATH": "/usr/bin:/bin"}, config=config or {},
                 provider_factory=(lambda env: provider) if provider else None)
    if provider is None:
        from agency.providers import provider_from_env
        tb.provider_factory = provider_from_env
    return Store(repo / "agency" / "out" / "agency.db"), tb


def readme_diff(repo, new="Hello, world.") -> str:
    old = (repo / "README.md").read_text()
    (repo / "README.md").write_text(old.replace("Hello.", new))
    d = git(repo, "diff")
    git(repo, "checkout", "--", "README.md")
    return d


def run(store, tb, name, **params):
    mid = orch.plan(store, tb, name, params=params)
    return mid, orch.Orchestrator(store, tb).run(mid)


# --------------------------------------------------------------------------- code changes
def test_patch_needs_approval_then_commits_on_isolated_branch(repo):
    store, tb = make(repo)
    mid, state = run(store, tb, "patch", patch=readme_diff(repo), branch="hello", role="docs")
    assert state == "NEEDS_APPROVAL" and store.calls(mid) == []
    orch.approve(store, f"{mid}.apply", "owner")
    assert orch.Orchestrator(store, tb).run(mid) == "COMPLETED"
    wt = repo / "agency/out/worktrees/hello"
    assert "Hello, world." in (wt / "README.md").read_text()
    assert "Hello." in (repo / "README.md").read_text()  # main working tree untouched
    assert git(repo, "status", "--porcelain") == ""
    assert "agency (docs): hello" in git(repo, "log", "-1", "--format=%s", "agency/hello")
    apply = store.task(f"{mid}.apply")
    assert "confirmed by git" in apply["verification"]
    assert "Branches created" in markdown(store, mid) and "agency/hello" in markdown(store, mid)


def test_tests_run_against_the_branch_not_main(repo):
    store, tb = make(repo)
    (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 3\n")
    broken = git(repo, "diff")
    git(repo, "checkout", "--", "tests/test_ok.py")
    mid, _ = run(store, tb, "patch", patch=broken, branch="breaks-test", role="qa")
    orch.approve(store, f"{mid}.apply", "owner")
    assert orch.Orchestrator(store, tb).run(mid) == "FAILED"
    assert store.task(f"{mid}.test")["state"] == "FAILED" and "1 failed" in store.task(f"{mid}.test")["summary"]
    assert tb.call(ROLES["qa"], "run_tests", {"suite": "bot"}).status == "PASS"  # main still passes


def test_ownership_and_protected_paths(repo):
    _, tb = make(repo)
    d = readme_diff(repo)
    with pytest.raises(PermissionDenied, match="does not own README.md"):
        tb.call(ROLES["backend"], "apply_patch", {"branch": "x", "patch": d}, approved=True)
    ci = "--- a/.github/workflows/test.yml\n+++ b/.github/workflows/test.yml\n@@ -1 +1 @@\n-a\n+b\n"
    with pytest.raises(PermissionDenied, match="protected"):
        tb.call(ROLES["fullstack"], "apply_patch", {"branch": "x", "patch": ci}, approved=True)
    for sneaky in ("agency/roles.py", "agency/./roles.py", "tests/../agency/roles.py"):
        with pytest.raises(PermissionDenied, match="protected"):
            tb.call(ROLES["fullstack"], "apply_patch", {"branch": "x", "patch": ci.replace(
                ".github/workflows/test.yml", sneaky)}, approved=True)
    with pytest.raises(ApprovalRequired):
        tb.call(ROLES["docs"], "apply_patch", {"branch": "x", "patch": d})
    with pytest.raises(InvalidInput):
        tb.call(ROLES["docs"], "apply_patch", {"branch": "../evil", "patch": d}, approved=True)
    assert git(repo, "branch", "--list", "agency/*") == ""


def test_bad_patch_leaves_nothing_behind_and_duplicate_branch_is_blocked(repo):
    _, tb = make(repo)
    bad = "--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n # Nope\n-not there\n+x\n"
    r = tb.call(ROLES["docs"], "apply_patch", {"branch": "bad", "patch": bad}, approved=True)
    assert r.status == "FAIL" and "nothing kept" in r.summary
    assert git(repo, "branch", "--list", "agency/bad") == "" and not (repo / "agency/out/worktrees/bad").exists()
    d = readme_diff(repo)
    assert tb.call(ROLES["docs"], "apply_patch", {"branch": "ok", "patch": d}, approved=True).status == "PASS"
    assert tb.call(ROLES["docs"], "apply_patch", {"branch": "ok", "patch": d}, approved=True).status == "BLOCKED"


def test_change_playbook_with_llm_patch(repo):
    d = readme_diff(repo)
    store, tb = make(repo, FakeProvider(f"Here you go:\n```diff\n{d}```"))
    mid, state = run(store, tb, "change", request="greet the world", paths="README.md", branch="greet")
    assert state == "NEEDS_APPROVAL"
    orch.approve(store, f"{mid}.propose", "owner")
    assert orch.Orchestrator(store, tb).run(mid) == "NEEDS_APPROVAL"  # the commit needs its own approval
    assert store.task(f"{mid}.propose")["state"] == "COMPLETED"
    orch.approve(store, f"{mid}.apply", "owner")
    assert orch.Orchestrator(store, tb).run(mid) == "COMPLETED"
    assert "Hello, world." in (repo / "agency/out/worktrees/greet/README.md").read_text()
    assert "greet the world" in tb.provider_factory(None).prompts[0]


def test_llm_patch_touching_unlisted_file_is_rejected(repo):
    other = "--- a/bot.py\n+++ b/bot.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    _, tb = make(repo, FakeProvider(f"```diff\n{other}```"))
    r = tb.call(ROLES["ai_engineer"], "propose_patch", {"request": "r", "paths": ["README.md"]}, approved=True)
    assert r.status == "FAIL" and "wasn't given: bot.py" in r.summary
    assert patch_paths(other) == ["bot.py"]


def test_push_needs_approval_and_reaches_remote(repo, tmp_path_factory):
    remote = tmp_path_factory.mktemp("remote")
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    git(repo, "remote", "add", "origin", str(remote))
    store, tb = make(repo)
    assert tb.call(ROLES["docs"], "apply_patch", {"branch": "pushme", "patch": readme_diff(repo)},
                   approved=True).status == "PASS"
    mid, state = run(store, tb, "ship", branch="pushme")
    assert state == "NEEDS_APPROVAL"
    assert subprocess.run(["git", "-C", str(remote), "branch"], capture_output=True, text=True).stdout == ""
    orch.approve(store, f"{mid}.push", "owner")
    assert orch.Orchestrator(store, tb).run(mid) == "COMPLETED"
    assert "agency/pushme" in subprocess.run(["git", "-C", str(remote), "branch"], capture_output=True,
                                             text=True).stdout


# --------------------------------------------------------------------------- planner
PLAN = {"title": "Check the repo", "steps": [
    {"id": "tests", "title": "Run tests", "role": "qa", "tool": "run_tests", "args": {"suite": "bot"}},
    {"id": "secrets", "title": "Scan secrets", "role": "security", "tool": "secret_scan", "args": {}}]}


def test_planner_plan_waits_for_approval_then_runs(repo):
    bad = {"title": "x", "steps": [{"id": "a", "role": "qa", "tool": "secret_scan", "args": {}}]}
    fake = FakeProvider(json.dumps(bad), "```json\n" + json.dumps(PLAN) + "\n```")
    store, tb = make(repo)
    pb, used = planner.propose("check everything", tb, fake)
    assert used["llm_calls"] == 2 and "not permitted" in fake.prompts[1]  # rejection fed back once
    mid = orch.plan_steps(store, tb, "llm", pb, requires_approval=True, planner_usage=used)
    assert orch.Orchestrator(store, tb).run(mid) == "NEEDS_APPROVAL" and store.calls(mid) == []
    orch.approve_mission(store, mid, "owner")
    assert orch.Orchestrator(store, tb).run(mid) == "COMPLETED"
    u = usage(store, mid, {"stub-1": {"input": 3.0, "output": 15.0}})
    assert u["llm_calls"] == 2 and u["prompt_tokens"] == 200 and u["cost"] == pytest.approx(0.0012)
    assert "Plan approval: owner" in markdown(store, mid)


def test_planner_gives_up_after_two_bad_plans(repo):
    bad = json.dumps({"steps": [{"id": "a", "role": "qa", "tool": "rm_rf", "args": {}}]})
    fake = FakeProvider(bad, bad)
    _, tb = make(repo)
    with pytest.raises(orch.PlanError, match="2 tries"):
        planner.propose("x", tb, fake)
    assert fake.replies == []


def test_missing_params_and_empty_playbooks_are_rejected(repo):
    store, tb = make(repo)
    with pytest.raises(orch.PlanError, match="missing parameter"):
        orch.plan(store, tb, "ship")
    with pytest.raises(orch.PlanError, match="no steps"):
        orch.plan(store, tb, "deploy-check")  # no health_urls configured


# --------------------------------------------------------------------------- cancel kills
def test_cancel_kills_a_running_subprocess(repo):
    (repo / "slow").mkdir()
    (repo / "slow" / "test_slow.py").write_text("import time\ndef test_slow():\n    time.sleep(60)\n")
    store, tb = make(repo)
    mid = orch.plan_steps(store, tb, "t", Playbook("t", (Step("s", "", "qa", "run_tests", {"suite": "slow"}),)))
    result = {}
    th = threading.Thread(target=lambda: result.setdefault("state", orch.Orchestrator(Store(store.path), tb).run(mid)))
    t0 = time.monotonic()
    th.start()
    time.sleep(2)
    orch.cancel(store, mid, "owner")
    th.join(20)
    assert result["state"] == "CANCELLED" and time.monotonic() - t0 < 15
    call = store.last_call(f"{mid}.s")
    assert call["summary"] == "cancelled" and store.task(f"{mid}.s")["state"] == "CANCELLED"


def test_timeout_kills_the_process_group(repo):
    _, tb = make(repo)
    t0 = time.monotonic()
    code, _, res = tb._run(["bash", "-c", "sleep 30 & sleep 30"], repo, timeout=1)
    assert code is None and "timed out" in res.summary and time.monotonic() - t0 < 5


# --------------------------------------------------------------------------- health URLs and MCP
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        code = 200 if self.path == "/ok" else 500
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def test_http_health_is_allowlisted(repo):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ok, bad = f"http://127.0.0.1:{srv.server_port}/ok", f"http://127.0.0.1:{srv.server_port}/bad"
    try:
        store, tb = make(repo, config={"health_urls": [ok, bad]})
        mid, state = run(store, tb, "deploy-check")
        with pytest.raises(InvalidInput):
            tb.call(ROLES["sre"], "http_health", {"url": "http://169.254.169.254/latest/meta-data"})
    finally:
        srv.shutdown()
    assert state == "FAILED"
    t = {t["step"]: t for t in store.tasks(mid)}
    assert t["url1"]["state"] == "COMPLETED" and t["url1"]["verification"] == "HTTP 200"
    assert t["url2"]["state"] == "FAILED" and "500" in t["url2"]["summary"]
    _, empty = make(repo)
    with pytest.raises(InvalidInput):  # no allowlist at all means nothing is reachable
        empty.call(ROLES["sre"], "http_health", {"url": ok})


FAKE_MCP = textwrap.dedent("""
    import json, sys
    for line in sys.stdin:
        msg = json.loads(line)
        if "id" not in msg:
            continue
        m = msg["method"]
        if m == "initialize":
            res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
        elif m == "tools/list":
            res = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
        elif m == "tools/call":
            res = {"content": [{"type": "text", "text": "echo:" + json.dumps(msg["params"]["arguments"])}]}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"message": "no"}}), flush=True)
            continue
        print("log line that is not JSON", flush=True)
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
""")


def test_mcp_list_and_call_against_a_stdio_server(repo):
    (repo / "fake_mcp.py").write_text(FAKE_MCP)
    _, tb = make(repo, config={"mcp_servers": {"fake": [sys.executable, "fake_mcp.py"]}})
    r = tb.call(ROLES["integration"], "mcp_list_tools", {"server": "fake"})
    assert r.status == "PASS" and r.evidence["tools"] == ["echo"]
    with pytest.raises(ApprovalRequired):
        tb.call(ROLES["integration"], "mcp_call", {"server": "fake", "tool": "echo"})
    r = tb.call(ROLES["integration"], "mcp_call", {"server": "fake", "tool": "echo", "arguments": '{"a": 1}'},
                approved=True)
    assert r.status == "PASS" and r.output == 'echo:{"a": 1}'
    with pytest.raises(InvalidInput):
        tb.call(ROLES["integration"], "mcp_list_tools", {"server": "other"})
    with pytest.raises(PermissionDenied):
        tb.call(ROLES["qa"], "mcp_list_tools", {"server": "fake"})


# --------------------------------------------------------------------------- research, perf, bandit
def test_pypi_info_parses_registry_json(repo, monkeypatch):
    import agency.tools as tools_mod

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self, *a):
            return json.dumps({"info": {"name": "demo", "version": "1.2.3", "license_expression": "MIT",
                                        "requires_python": ">=3.9"},
                               "urls": [{"upload_time_iso_8601": "2026-01-02T00:00:00Z"}]}).encode()
    monkeypatch.setattr(tools_mod.urllib.request, "urlopen", lambda url, timeout: Resp())
    _, tb = make(repo)
    r = tb.call(ROLES["research"], "pypi_info", {"package": "demo"})
    assert r.status == "PASS" and r.evidence["version"] == "1.2.3" and r.evidence["license"] == "MIT"
    with pytest.raises(InvalidInput):
        tb.call(ROLES["research"], "pypi_info", {"package": "x; rm -rf /"})


def test_pytest_durations_reports_slowest(repo):
    _, tb = make(repo)
    r = tb.call(ROLES["performance"], "pytest_durations", {"suite": "bot"})
    assert r.status == "PASS" and r.evidence["wall_seconds"] > 0 and "slowest" in r.evidence


def test_bandit_flags_eval(repo):
    _, tb = make(repo)
    r = tb.call(ROLES["security"], "bandit", {"paths": ["bot.py"]})
    if r.status == "BLOCKED":
        pytest.skip("bandit not installed")
    assert r.status == "PASS"
    (repo / "bot.py").write_text("import sys\neval(sys.argv[1])\n")
    assert tb.call(ROLES["security"], "bandit", {"paths": ["bot.py"]}).status == "FAIL"


# --------------------------------------------------------------------------- dashboard actions
def post(url, data, host=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_dashboard_actions_require_csrf_and_local_host(repo):
    store, tb = make(repo)
    (repo / "bot.py").write_text("x = 2\n")  # an uncommitted change, so the review has a diff to send
    mid, _ = run(store, tb, "review")  # waits for approval of llm-review
    srv = serve(store, tb, port=0, actions=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        page = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"{base}/mission/{mid}").read().decode()
        token = page.split("name=csrf value='")[1].split("'")[0]
        approve = {"task": f"{mid}.llm-review"}
        assert post(f"{base}/mission/{mid}/approve", approve)[0] == 403  # no token
        assert post(f"{base}/mission/{mid}/approve", {**approve, "csrf": "wrong"})[0] == 403
        assert post(f"{base}/mission/{mid}/approve", {**approve, "csrf": token}, host="evil.example")[0] == 403
        code, _ = post(f"{base}/mission/{mid}/approve", {**approve, "csrf": token})
        assert code == 200  # 303 followed to the mission page
        for _ in range(50):
            if Store(store.path).task(f"{mid}.llm-review")["state"] in ("BLOCKED", "COMPLETED"):
                break
            time.sleep(0.1)
    finally:
        srv.shutdown()
    t = Store(store.path).task(f"{mid}.llm-review")
    assert t["approved_by"].endswith("(dashboard)") and t["state"] == "BLOCKED"  # no LLM key in this test


def test_read_only_dashboard_refuses_posts(repo):
    store, tb = make(repo)
    srv = serve(store, tb, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert post(f"http://127.0.0.1:{srv.server_port}/run", {"playbook": "health"})[0] == 405
    finally:
        srv.shutdown()
    assert store.missions() == []


# --------------------------------------------------------------------------- worker, migration
def test_worker_resumes_approved_work_and_never_approves(repo):
    store, tb = make(repo)
    ready = orch.plan_steps(store, tb, "t", Playbook("t", (Step("s", "", "devops", "git_status"),)))
    waiting = orch.plan_steps(store, tb, "llm", Playbook("p", (Step("s", "", "devops", "git_status"),)),
                              requires_approval=True)
    wk = Worker(store, tb, playbook=None, every=3600)
    assert wk.tick() == [(ready, "COMPLETED")]
    assert store.mission(waiting)["state"] == "NEEDS_APPROVAL" and store.calls(waiting) == []
    assert store.heartbeats()[0]["worker"] == wk.orch.worker
    assert wk.tick() == []  # nothing left to do, nothing scheduled


def test_old_database_is_migrated(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE missions (id TEXT PRIMARY KEY, playbook TEXT NOT NULL, title TEXT NOT NULL, "
                "state TEXT NOT NULL, call_budget INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    con.execute("INSERT INTO missions VALUES ('m-0000000000','health','t','COMPLETED',50,1,1)")
    con.commit()
    con.close()
    store = Store(db)
    m = store.mission("m-0000000000")
    assert m["requires_approval"] == 0 and m["params"] == "{}" and m["state"] == State.COMPLETED.value


def test_provider_refuses_non_http_urls():
    from agency.providers import OpenAICompatible, ProviderUnavailable
    with pytest.raises(ProviderUnavailable, match="http"):
        OpenAICompatible("file:///etc", "k" * 10, "m")


def test_live_script_starts_one_worker_and_stops_it(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "agency-live.sh"
    env = {"PATH": "/usr/bin:/bin", "AGENCY_LIVE_PYTHON": sys.executable, "AGENCY_LIVE_PLAYBOOK": "",
           "AGENCY_LIVE_DB": str(tmp_path / "agency.db")}

    def live(cmd):
        return subprocess.run(["bash", str(script), cmd], env=env, capture_output=True, text=True, timeout=60)

    try:
        first = live("start")
        assert first.returncode == 0, first.stderr
        pid = (tmp_path / "worker.pid").read_text().strip()
        assert f"running (pid {pid}" in first.stdout
        assert live("start").returncode == 0 and (tmp_path / "worker.pid").read_text().strip() == pid  # no 2nd
        assert live("status").returncode == 0
    finally:
        assert "stopped" in live("stop").stdout
    status = live("status")
    assert status.returncode == 1 and "not running" in status.stdout
    assert "agency worker stopped" in (tmp_path / "worker.log").read_text()  # clean SIGTERM shutdown
