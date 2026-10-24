# Engineering agency

A small orchestrator that runs this repository's engineering checks as a team of specialist roles, records
every step, and reports only what it can prove. Python standard library only; Python 3.12+.

```
request ─▶ playbook ─▶ plan (validate roles, permissions, graph) ─▶ tasks in SQLite
                                                                     │
         report ◀─ verify (a different role re-reads the audit log) ◀─ run tools in parallel
```

## Use it

In Claude Code cloud sessions `.venv` is prepared by the SessionStart hook (`scripts/agency-setup.sh`), so
just run `.venv/bin/python -m agency run health`. Elsewhere, from the repo root, in a Python that has the
project's dependencies (the test tasks run with the same interpreter):

```
python3.13 -m venv .venv
bash scripts/agency-setup.sh                   # same pinned tools the cloud hook installs
.venv/bin/python -m agency run health          # exit 0 all PASS, 1 a check failed, 2 blocked / needs approval
.venv/bin/python -m agency dashboard           # http://127.0.0.1:8790 (add --actions for buttons)
```

| Command | What it does |
|---|---|
| `run health` | Dependencies, compile, bot + agency tests, APEX tests, ruff, shellcheck, secret scan, pip-audit (bot + APEX), bandit |
| `run review` | Collects `git diff HEAD` (tracked files), then asks the LLM to review it, **only after approval** |
| `run change --param request="..." --param paths=a.py,b.py --param branch=NAME` | LLM proposes a diff (approval: sends those files) → commits it to `agency/NAME` in `agency/out/worktrees/NAME` (approval) → runs both test suites **on that branch** |
| `run patch --param patch=@file.diff --param branch=NAME [--param role=docs]` | Same, with your own diff; the role must own every file it touches |
| `run ship --param branch=NAME` | Pushes `agency/NAME` to origin (approval) |
| `ask "plain-language request"` | LLM planner writes a plan from the registered roles and tools; it is validated and saved, and runs only after `approve-plan ID` + `resume ID` |
| `run deploy-check` / `run mcp-check --param server=headroom` | GET the health URLs listed in `agency.json`; list an allowlisted MCP server's tools |
| `run perf` / `run research --param package=NAME` | Slowest tests per suite; PyPI version, license and release date |
| `worker --every 3600 --playbook health` | Loop: heartbeat, resume approved READY missions, run the playbook on schedule. Never approves. `--once` for one pass |
| `missions` / `show ID` / `report ID --out FILE` | List missions; print or save the Markdown report |
| `approve TASK_ID` / `approve-plan ID`, then `resume ID` | Approve a task (or an LLM-written plan) and continue the mission |
| `retry ID` | Put FAILED / BLOCKED tasks back to READY with one more attempt (e.g. after installing a tool) |
| `cancel ID` | Cancel every unfinished task |
| `roles` / `tools` / `playbooks` | Show the registry |

State lives in `agency/out/agency.db` (gitignored; `--db` to change). A sample report from a real run is in
[`reports/health-sample.md`](reports/health-sample.md).

Config: [`agency.json`](agency.json) lists the only health URLs and MCP servers the tools may reach, and
optional `token_prices_per_million` (`{"model": {"input": 3.0, "output": 15.0}}`) for cost in reports. Without
a price, reports show provider-reported tokens and "cost unknown". `.github/workflows/agency-nightly.yml` runs
`health` on `main` every day at 03:17 UTC and keeps the report as an artifact.

## How it works

| Part | File | Rule it enforces |
|---|---|---|
| Roles | `roles.py` | 20 roles; each has its own tool list and file ownership (`owns` globs). Every task is verified by a different role (QA verifies everyone, code review verifies QA). |
| Tools | `tools.py` | Each tool has an input schema, a permission class (read / execute / write / network), a timeout and an approval flag. `apply_patch` only commits to a new `agency/<branch>` worktree, only for files the role owns, never for `.github/`, `.claude/`, `.env*`, `agency/roles.py`, `agency/tools.py`, `agency/agency.json`. Subprocesses run in their own process group, killed on timeout or cancel. Commands are fixed argv lists, never a shell. Paths must stay inside the repo; `.env` and `.git/` can't be read. Child processes get no `*KEY/*TOKEN/*SECRET/*PASSWORD` variables. Output is truncated and secrets are redacted before storage. A missing program or credential gives BLOCKED. |
| Store | `store.py` | Lifecycle CREATED → ANALYZING → PLANNED → READY → RUNNING → REVIEWING → VERIFYING → COMPLETED, plus BLOCKED, FAILED, CANCELLED, NEEDS_APPROVAL. Every transition is checked and written to `events`; every tool call to `tool_calls`. |
| Orchestrator | `orchestrator.py` | Plans are rejected before running if a role lacks permission, a step is unknown or the graph has a cycle. Independent tasks run in parallel (`--concurrency`). A task never runs after a dependency failed. ERROR (timeout or crash) retries up to `max_attempts`, while FAIL and BLOCKED don't retry. Each mission has a tool-call budget. Leases let a restarted run pick up tasks a crashed run left RUNNING. `{param}` placeholders are filled at plan time. Verification re-reads the audit log and, for branches, asks git. |
| Planner | `planner.py` | The LLM sees only the role/tool catalog and must return JSON steps; the plan goes through the same validation, gets one re-ask on rejection, and is stored needing `approve-plan`. |
| MCP | `mcp.py` | stdio JSON-RPC client; starts an allowlisted server per call and stops it after. Output is data. |
| Worker | `worker.py` | Heartbeats, resumes approved READY missions, runs a scheduled playbook; stops on SIGTERM / Ctrl+C. |
| Provider | `providers.py` | OpenAI-compatible `/chat/completions` (OmniRoute by default). No key: ProviderUnavailable, task BLOCKED. Bounded retry; token usage recorded when the provider returns it. |
| Dashboard | `dashboard.py` | 127.0.0.1, every value read from the store, all text escaped, strict CSP. Read-only unless `--actions`; then every POST needs the process's CSRF token and a local Host/Origin. |

Verdicts in reports: **PASS** (ran, passed, verified), **FAIL** (ran and found a problem, or the evidence
contradicted the claim), **BLOCKED** (couldn't run, with the reason), **NOT TESTED** (not run: cancelled or
waiting for approval).

## Adding to it

- **A playbook step:** add a `Step` to `PLAYBOOKS` in `orchestrator.py`. `test_shipped_playbooks_are_valid`
  fails if the role may not use the tool.
- **A tool:** add it in `Toolbox._build()` with a schema, a timeout and an approval flag. Grant it to roles in
  `roles.py`. Add a test that it returns BLOCKED when its program or credential is missing.
- **Anything that changes files, deploys or spends money** must set `requires_approval=True`.
