"""Plans a playbook into a mission and runs its task graph.

Planning rejects a playbook before anything runs if a step names an unknown role or tool, gives a role a tool
outside its permissions, depends on a missing step, or forms a cycle. Each task gets a verifier that is a
different role from the one running it.

Running:
- Tasks whose dependencies all COMPLETED run in parallel, up to `concurrency`. A task whose dependency ended
  FAILED, BLOCKED or CANCELLED becomes BLOCKED with the reason; it is never run on bad inputs.
- Handoffs: a step can take an argument from a dependency's evidence (`handoff={"diff": ("diff", "diff")}`).
- A tool call returning ERROR (timeout, crash) is retried up to the task's max_attempts; FAIL and BLOCKED
  are not retried, because re-running a deterministic failure proves nothing.
- Every mission has a tool-call budget; when it is spent, remaining tasks are BLOCKED.
- Tools that need approval leave their task in NEEDS_APPROVAL until `approve()` is called by a human.
- Verification: after a call, the verifier re-reads the audit row (not the runner's in-memory result) and
  checks the verdict against the evidence, e.g. that a PASS for tests has exit code 0, passes and no failures.
- Cancellation is checked every second: running subprocesses are killed (whole process group) and their
  calls are recorded in the audit log without changing state.
- Parameters: `{name}` in a step argument is filled from the mission's params at plan time; a list argument
  given as "{name}" is split on commas. Missing params reject the plan.
- Missions planned by the LLM planner (`plan_steps(..., requires_approval=True)`) don't run until a human
  calls `approve_mission`, even though each step was already validated.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import socket
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from .roles import ROLES, VERIFIER
from .store import FINAL, State, Store
from .tools import (
    ApprovalRequired,
    InvalidInput,
    PermissionDenied,
    Toolbox,
    ToolResult,
    pytest_counts,
)


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    role: str
    tool: str
    args: dict = field(default_factory=dict)
    after: tuple[str, ...] = ()
    handoff: dict = field(default_factory=dict)  # arg name -> (step id, evidence key)


@dataclass(frozen=True)
class Playbook:
    title: str
    steps: tuple[Step, ...]


SHELL_SCRIPTS = ["service/install.sh", "service/test-service.sh", "termux/install.sh", "termux/test-termux.sh",
                 "scripts/agency-setup.sh"]

PLAYBOOKS: dict[str, Playbook] = {
    "health": Playbook("Repository health check: dependencies, tests, lint, secrets", (
        Step("git", "Working tree status", "devops", "git_status"),
        Step("bot-deps", "Bot dependencies installed", "release", "dependency_inspect",
             {"manifest": "requirements.txt"}),
        Step("apex-deps", "APEX dependencies installed", "release", "dependency_inspect",
             {"manifest": "apex/requirements.txt"}),
        Step("compile", "Bot and agency compile", "devops", "py_compile",
             {"paths": ["bot.py", "agency/orchestrator.py", "agency/tools.py", "agency/store.py"]}),
        Step("bot-tests", "Bot, agency and skill tests", "qa", "run_tests", {"suite": "bot"}, ("bot-deps",)),
        Step("apex-tests", "APEX test suite", "qa", "run_tests", {"suite": "apex"}, ("apex-deps",)),
        Step("lint", "Lint the agency package", "code_review", "ruff", {"paths": ["agency"]}),
        Step("shell", "Lint install scripts", "devops", "shellcheck", {"paths": SHELL_SCRIPTS}),
        Step("secrets", "No credentials in tracked files", "security", "secret_scan"),
        Step("audit", "Known vulnerabilities in bot dependencies", "security", "pip_audit",
             {"manifest": "requirements.txt"}, ("bot-deps",)),
        Step("apex-audit", "Known vulnerabilities in APEX dependencies", "security", "pip_audit",
             {"manifest": "apex/requirements.txt"}, ("apex-deps",)),
        Step("sast", "Static security analysis (bandit, medium+)", "security", "bandit",
             {"paths": ["bot.py", "agency", "apex/apex"]}),
    )),
    "change": Playbook("LLM-written change on its own branch: propose, apply, test (approvals: send code, commit)", (
        Step("propose", "Propose a diff for {request}", "ai_engineer", "propose_patch",
             {"request": "{request}", "paths": "{paths}"}),
        Step("apply", "Commit the diff to agency/{branch}", "fullstack", "apply_patch", {"branch": "{branch}"},
             ("propose",), {"patch": ("propose", "patch")}),
        Step("test", "Bot and agency tests on the branch", "qa", "run_tests", {"suite": "bot"}, ("apply",),
             {"worktree": ("apply", "worktree")}),
        Step("apex-test", "APEX tests on the branch", "ml_engineer", "run_tests", {"suite": "apex"}, ("apply",),
             {"worktree": ("apply", "worktree")}),
    )),
    "patch": Playbook("Human-written diff on its own branch: apply, test (approval: commit)", (
        Step("apply", "Commit the diff to agency/{branch}", "{role}", "apply_patch",
             {"branch": "{branch}", "patch": "{patch}"}),
        Step("test", "Bot and agency tests on the branch", "qa", "run_tests", {"suite": "bot"}, ("apply",),
             {"worktree": ("apply", "worktree")}),
        Step("apex-test", "APEX tests on the branch", "ml_engineer", "run_tests", {"suite": "apex"}, ("apply",),
             {"worktree": ("apply", "worktree")}),
    )),
    "ship": Playbook("Push a tested agency/{branch} to GitHub (approval: push)", (
        Step("push", "Push agency/{branch}", "release", "git_push", {"branch": "{branch}"}),
    )),
    "perf": Playbook("Measure test-suite timings", (
        Step("bot", "Time bot and agency tests", "performance", "pytest_durations", {"suite": "bot"}),
        Step("apex", "Time APEX tests", "performance", "pytest_durations", {"suite": "apex"}),
    )),
    "research": Playbook("PyPI facts for {package}", (
        Step("pypi", "Version, license and release date of {package}", "research", "pypi_info",
             {"package": "{package}"}),
    )),
    "mcp-check": Playbook("List the tools of MCP server {server}", (
        Step("list", "Connect and list tools on {server}", "integration", "mcp_list_tools", {"server": "{server}"}),
    )),
    "review": Playbook("Model-assisted review of uncommitted changes (needs approval: sends the diff out)", (
        Step("diff", "Collect the diff", "code_review", "git_diff"),
        Step("llm-review", "LLM review of the diff", "ai_engineer", "llm_review", {}, ("diff",),
             {"diff": ("diff", "diff")}),
    )),
}

DEFAULT_PARAMS = {"patch": {"role": "fullstack"}}


def dynamic_playbook(name: str, toolbox: Toolbox) -> Playbook | None:
    """Playbooks built from config at plan time."""
    if name == "deploy-check":
        urls = toolbox.config.get("health_urls", [])
        return Playbook("Health endpoints from agency.json", tuple(
            Step(f"url{i}", f"GET {u}", "sre", "http_health", {"url": u}) for i, u in enumerate(urls, 1)))
    return None


def playbook_names() -> list[str]:
    return sorted([*PLAYBOOKS, "deploy-check"])


def _fill(value, params: dict, list_typed: bool):
    if isinstance(value, list):
        return [_fill(v, params, False) for v in value]
    if not isinstance(value, str):
        return value
    whole = re.fullmatch(r"\{(\w+)\}", value)
    if whole and list_typed:
        return [v.strip() for v in str(params[whole.group(1)]).split(",") if v.strip()]
    if whole:
        return params[whole.group(1)]
    return re.sub(r"\{(\w+)\}", lambda m: str(params[m.group(1)]), value)


def with_params(pb: Playbook, params: dict, toolbox: Toolbox) -> Playbook:
    used = set()
    for s in pb.steps:
        for text in [s.title, s.role, *map(json.dumps, s.args.values())]:
            used |= set(re.findall(r"\{(\w+)\}", text))
    missing = sorted(used - set(params))
    if missing:
        raise PlanError(f"missing parameter(s): {', '.join(missing)} (pass --param name=value)")
    steps = []
    for s in pb.steps:
        tool = toolbox.tools.get(s.tool)
        args = {k: _fill(v, params, bool(tool and tool.params.get(k) and tool.params[k].type is list))
                for k, v in s.args.items()}
        steps.append(dataclasses.replace(s, title=_fill(s.title, params, False), role=_fill(s.role, params, False),
                                         args=args))
    return Playbook(_fill(pb.title, params, False), tuple(steps))


VERDICT = {State.COMPLETED: "PASS", State.FAILED: "FAIL", State.BLOCKED: "BLOCKED"}


def verdict(task) -> str:
    return VERDICT.get(State(task["state"]), "NOT TESTED")


def validate_playbook(pb: Playbook, toolbox: Toolbox) -> list[str]:
    """Return steps in dependency order, or raise PlanError."""
    ids = [s.id for s in pb.steps]
    if not ids:
        raise PlanError("playbook has no steps (an empty mission would prove nothing)")
    if len(set(ids)) != len(ids):
        raise PlanError("duplicate step ids")
    by_id = {s.id: s for s in pb.steps}
    for s in pb.steps:
        role = ROLES.get(s.role)
        if role is None:
            raise PlanError(f"{s.id}: unknown role {s.role!r}")
        if s.tool not in toolbox.tools:
            raise PlanError(f"{s.id}: unknown tool {s.tool!r}")
        if s.tool not in role.tools:
            raise PlanError(f"{s.id}: role {s.role} is not permitted to use {s.tool}")
        if VERIFIER[s.role] == s.role:
            raise PlanError(f"{s.id}: a role cannot verify its own work")
        for dep in s.after:
            if dep not in by_id:
                raise PlanError(f"{s.id}: depends on unknown step {dep!r}")
        for arg, (src, _key) in s.handoff.items():
            if src not in s.after:
                raise PlanError(f"{s.id}: handoff for {arg} comes from {src}, which is not a dependency")
        try:
            toolbox.tools[s.tool].validate(s.args, deferred=frozenset(s.handoff))
        except InvalidInput as e:
            raise PlanError(f"{s.id}: {e}") from None
    order, done, pending = [], set(), list(ids)
    while pending:
        ready = [i for i in pending if all(d in done for d in by_id[i].after)]
        if not ready:
            raise PlanError(f"dependency cycle among {sorted(pending)}")
        for i in ready:
            order.append(i)
            done.add(i)
            pending.remove(i)
    return order


def plan(store: Store, toolbox: Toolbox, name: str, call_budget: int = 50, max_attempts: int = 2,
         params: dict | None = None) -> str:
    pb = PLAYBOOKS.get(name) or dynamic_playbook(name, toolbox)
    if pb is None:
        raise PlanError(f"unknown playbook {name!r}; choose from {playbook_names()}")
    params = {**DEFAULT_PARAMS.get(name, {}), **(params or {})}
    return plan_steps(store, toolbox, name, pb, call_budget, max_attempts, params)


def plan_steps(store: Store, toolbox: Toolbox, name: str, pb: Playbook, call_budget: int = 50,
               max_attempts: int = 2, params: dict | None = None, requires_approval: bool = False,
               planner_usage: dict | None = None) -> str:
    params = params or {}
    shown = {k: (v if len(str(v)) < 200 else f"<{len(str(v))} chars>") for k, v in params.items()}
    mid = store.create_mission(name, pb.title, call_budget, shown, requires_approval, planner_usage)
    store.move_mission(mid, State.ANALYZING, "validating roles, permissions and dependency graph")
    try:
        pb = with_params(pb, params, toolbox)
        store.db.execute("UPDATE missions SET title=? WHERE id=?", (pb.title, mid))
        order = validate_playbook(pb, toolbox)
    except PlanError as e:
        store.move_mission(mid, State.FAILED, f"plan rejected: {e}")
        raise
    by_id = {s.id: s for s in pb.steps}
    for sid in order:
        step = by_id[sid]
        tid = store.add_task(mid, step, VERIFIER[step.role], max_attempts)
        if toolbox.tools[step.tool].requires_approval:
            store.move_task(tid, State.NEEDS_APPROVAL, f"{step.tool} requires human approval")
        else:
            store.move_task(tid, State.READY)
    store.move_mission(mid, State.PLANNED, f"{len(order)} task(s)")
    if requires_approval:
        store.move_mission(mid, State.NEEDS_APPROVAL, "plan written by the LLM planner; a human must approve it")
    else:
        store.move_mission(mid, State.READY)
    return mid


def approve_mission(store: Store, mission_id: str, who: str) -> None:
    m = store.mission(mission_id)
    if not m["requires_approval"]:
        raise PlanError(f"{mission_id} has no mission-level approval; approve its tasks instead")
    store.move_mission(mission_id, State.READY, f"plan approved by {who}", approved_by=who)


def approve(store: Store, task_id: str, who: str) -> None:
    store.move_task(task_id, State.READY, f"approved by {who}", approved_by=who)
    mission = store.mission(store.task(task_id)["mission_id"])
    plan_pending = mission["requires_approval"] and not mission["approved_by"]
    if mission["state"] == State.NEEDS_APPROVAL.value and not plan_pending:
        store.move_mission(mission["id"], State.READY, f"approval from {who}")


def cancel(store: Store, mission_id: str, who: str) -> None:
    for t in store.tasks(mission_id):
        if State(t["state"]) not in FINAL:
            store.move_task(t["id"], State.CANCELLED, f"mission cancelled by {who}")
    if State(store.mission(mission_id)["state"]) not in {State.CANCELLED, State.COMPLETED, State.FAILED}:
        store.move_mission(mission_id, State.CANCELLED, f"cancelled by {who}")


def retry(store: Store, mission_id: str, who: str) -> list[str]:
    """Human retry: FAILED and BLOCKED tasks go back to READY with one more attempt allowed."""
    again = []
    for t in store.tasks(mission_id):
        if t["state"] in (State.FAILED.value, State.BLOCKED.value):
            store.move_task(t["id"], State.READY, f"retry requested by {who}", max_attempts=t["attempts"] + 1)
            again.append(t["id"])
    m = store.mission(mission_id)
    if again and m["state"] in (State.FAILED.value, State.BLOCKED.value):
        store.move_mission(mission_id, State.READY, f"retry requested by {who}")
    return again


def check_evidence(task, call, toolbox: Toolbox | None = None) -> tuple[bool, str]:
    """Independent check of a recorded call. Returns (verdict agrees with evidence, note).

    With a toolbox, claims about the repository are re-checked against git itself, not the recorded output."""
    if call is None:
        return False, "no audit record for this task"
    status, code = call["status"], call["exit_code"]
    ev = json.loads(call["evidence"] or "{}")
    if task["tool"] == "http_health" and status == "PASS":
        return 200 <= (ev.get("http_status") or 0) < 400, f"HTTP {ev.get('http_status')}"
    if task["tool"] == "apply_patch" and status == "PASS":
        if not (ev.get("branch") and ev.get("commit")):
            return False, "no branch/commit in evidence"
        if toolbox is not None:
            rc, out, _ = toolbox._run(["git", "rev-parse", "--verify", "--quiet", ev["branch"]], toolbox.root, 15)
            if rc != 0 or out.strip() != ev["commit"]:
                return False, f"git says {ev['branch']} is {out.strip() or 'missing'}, evidence says {ev['commit'][:10]}"
        return True, f"{ev['branch']} at {ev['commit'][:10]} confirmed by git"
    if task["tool"] == "run_tests":
        c = pytest_counts(call["output"])
        if status == "PASS":
            ok = code == 0 and c["passed"] > 0 and c["failed"] == 0 and c["errors"] == 0
        else:
            ok = code != 0 or c["passed"] == 0 or c["failed"] > 0 or c["errors"] > 0
        return ok, f"exit {code}; {c['passed']} passed, {c['failed']} failed, {c['errors']} errors"
    if status == "PASS":
        return code in (0, None), f"exit {code}"
    return True, f"exit {code}; failure recorded"


class Orchestrator:
    def __init__(self, store: Store, toolbox: Toolbox, concurrency: int = 4, lease_grace: float = 60.0,
                 worker: str | None = None):
        self.store, self.toolbox = store, toolbox
        self.concurrency, self.lease_grace = max(1, concurrency), lease_grace
        self.worker = worker or f"{socket.gethostname()}:{os.getpid()}"

    def _cancelled(self, mission_id: str) -> bool:
        return self.store.mission(mission_id)["state"] == State.CANCELLED.value

    def _args(self, task) -> dict:
        args = json.loads(task["args"])
        for arg, (src, key) in json.loads(task["handoff"]).items():
            call = self.store.last_call(f"{task['mission_id']}.{src}")
            args[arg] = json.loads(call["evidence"]).get(key, "") if call else ""
        return args

    def run(self, mission_id: str) -> str:
        store = self.store
        store.recover(mission_id)  # each recovered task gets an event
        m = store.mission(mission_id)
        if m["state"] == State.CANCELLED.value:
            return m["state"]
        if m["requires_approval"] and not m["approved_by"]:
            return m["state"]  # an LLM-written plan never runs before a human approves it
        self.toolbox.cancel_event.clear()
        if m["state"] in (State.NEEDS_APPROVAL.value, State.BLOCKED.value, State.FAILED.value):
            store.move_mission(mission_id, State.READY, "resumed")
        if store.mission(mission_id)["state"] == State.READY.value:
            store.move_mission(mission_id, State.RUNNING, f"worker {self.worker}")
        inflight: dict[Future, tuple] = {}
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            while True:
                if self._cancelled(mission_id):
                    self.toolbox.cancel_event.set()  # kill running subprocesses, then audit what they did
                    for fut, (task, _role, args, attempt, t0) in inflight.items():
                        self._finish(task, args, attempt, t0, fut.result())
                    break
                self._block_on_bad_deps(mission_id)
                for task in self._runnable(mission_id, exclude={v[0]["id"] for v in inflight.values()}):
                    if len(inflight) >= self.concurrency:
                        break
                    if store.call_count(mission_id) + len(inflight) >= store.mission(mission_id)["call_budget"]:
                        store.move_task(task["id"], State.BLOCKED, "mission tool-call budget exhausted")
                        continue
                    started = self._start(task)
                    inflight[pool.submit(self._execute, *started[:3])] = started
                if not inflight:
                    break
                finished, _ = wait(inflight, timeout=1.0, return_when=FIRST_COMPLETED)
                if not finished and self._cancelled(mission_id):
                    self.toolbox.cancel_event.set()  # kills running subprocesses; results are audited only
                for fut in finished:
                    task, _role, args, attempt, t0 = inflight.pop(fut)
                    self._finish(task, args, attempt, t0, fut.result())
        return self._finalize(mission_id)

    def _runnable(self, mission_id: str, exclude: set) -> list:
        tasks = self.store.tasks(mission_id)
        state = {t["step"]: t["state"] for t in tasks}
        return [t for t in tasks if t["state"] == State.READY.value and t["id"] not in exclude
                and all(state[d] == State.COMPLETED.value for d in json.loads(t["depends_on"]))]

    def _block_on_bad_deps(self, mission_id: str) -> None:
        tasks = self.store.tasks(mission_id)
        state = {t["step"]: t["state"] for t in tasks}
        bad = {State.FAILED.value, State.BLOCKED.value, State.CANCELLED.value}
        for t in tasks:
            if t["state"] == State.READY.value:
                failed = [d for d in json.loads(t["depends_on"]) if state[d] in bad]
                if failed:
                    self.store.move_task(t["id"], State.BLOCKED,
                                         "dependency did not pass: " + ", ".join(f"{d} {state[d]}" for d in failed))

    def _start(self, task):
        attempt = task["attempts"] + 1
        args = self._args(task)
        timeout = self.toolbox.tools[task["tool"]].timeout
        self.store.move_task(task["id"], State.RUNNING, f"attempt {attempt}/{task['max_attempts']} by {task['role']}",
                             attempts=attempt, lease_owner=self.worker,
                             lease_expires_at=self.store.clock() + timeout + self.lease_grace)
        return task, ROLES[task["role"]], args, attempt, time.time()

    def _execute(self, task, role, args) -> ToolResult | Exception:
        """Runs in a worker thread: only the tool call, no database access."""
        try:
            return self.toolbox.call(role, task["tool"], args, approved=bool(task["approved_by"]))
        except (PermissionDenied, InvalidInput, ApprovalRequired) as e:
            return e

    def _finish(self, task, args, attempt, t0, outcome) -> None:
        store, tid = self.store, task["id"]
        if isinstance(outcome, (PermissionDenied, InvalidInput)):
            outcome = ToolResult("FAIL", f"policy: {outcome}")
        elif isinstance(outcome, ApprovalRequired):
            store.move_task(tid, State.NEEDS_APPROVAL, str(outcome), lease_owner=None)
            return
        store.record_call(task, attempt, t0, args, outcome)
        if self._cancelled(task["mission_id"]) or store.task(tid)["state"] != State.RUNNING.value:
            return  # cancelled while running: the call is audited, state stays CANCELLED
        done = {"lease_owner": None, "lease_expires_at": None, "status": outcome.status, "summary": outcome.summary}
        if outcome.status == "ERROR":
            if attempt < task["max_attempts"]:
                store.move_task(tid, State.READY, f"attempt {attempt} errored, retrying: {outcome.summary}", **done)
            else:
                store.move_task(tid, State.FAILED, f"gave up after {attempt} attempt(s): {outcome.summary}", **done)
            return
        if outcome.status == "BLOCKED":
            store.move_task(tid, State.BLOCKED, outcome.summary, **done)
            return
        store.move_task(tid, State.REVIEWING, f"{outcome.status}: {outcome.summary}", **done)
        store.move_task(tid, State.VERIFYING, f"handed to {task['verifier']} for verification")
        agrees, note = check_evidence(task, store.last_call(tid), self.toolbox)
        if not agrees:
            store.move_task(tid, State.FAILED, f"{task['verifier']}: evidence contradicts {outcome.status} ({note})",
                            verification=f"MISMATCH: {note}")
        elif outcome.status == "PASS":
            store.move_task(tid, State.COMPLETED, f"{task['verifier']} verified: {note}", verification=note)
        else:
            store.move_task(tid, State.FAILED, f"{task['verifier']} confirmed the failure: {note}", verification=note)

    def _finalize(self, mission_id: str) -> str:
        store = self.store
        m = store.mission(mission_id)
        if m["state"] != State.RUNNING.value:
            return m["state"]
        states = {t["state"] for t in store.tasks(mission_id)}
        if State.NEEDS_APPROVAL.value in states:
            store.move_mission(mission_id, State.NEEDS_APPROVAL, "waiting for human approval")
        elif State.FAILED.value in states:
            store.move_mission(mission_id, State.VERIFYING)
            store.move_mission(mission_id, State.FAILED, "one or more checks failed")
        elif states - {State.COMPLETED.value}:
            store.move_mission(mission_id, State.BLOCKED, "some tasks could not run: " + ", ".join(sorted(states)))
        else:
            store.move_mission(mission_id, State.VERIFYING)
            store.move_mission(mission_id, State.COMPLETED, "every task passed and was verified")
        return store.mission(mission_id)["state"]
