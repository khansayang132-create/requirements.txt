# Engineering agency

A small orchestrator that runs this repository's engineering checks as a team of specialist roles, records
every step, and reports only what it can prove. Python standard library only; Python 3.12+.

```
request ─▶ playbook ─▶ plan (validate roles, permissions, graph) ─▶ tasks in SQLite
                                                                     │
         report ◀─ verify (a different role re-reads the audit log) ◀─ run tools in parallel
```

## Use it

From the repo root, in a Python that has the project's dependencies (the test tasks run with the same
interpreter):

```
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt -r apex/requirements.txt pytest ruff pip-audit shellcheck-py
.venv/bin/python -m agency run health          # exit 0 all PASS, 1 a check failed, 2 blocked / needs approval
.venv/bin/python -m agency dashboard           # http://127.0.0.1:8790
```

| Command | What it does |
|---|---|
| `run health` | Dependencies, compile, bot + agency tests, APEX tests, ruff, shellcheck, secret scan, pip-audit |
| `run review` | Collects `git diff HEAD` (tracked files), then asks the LLM to review it, **only after approval** |
| `missions` / `show ID` / `report ID --out FILE` | List missions; print or save the Markdown report |
| `approve TASK_ID` then `resume ID` | Approve a task waiting in NEEDS_APPROVAL and continue the mission |
| `retry ID` | Put FAILED / BLOCKED tasks back to READY with one more attempt (e.g. after installing a tool) |
| `cancel ID` | Cancel every unfinished task |
| `roles` / `tools` / `playbooks` | Show the registry |

State lives in `agency/out/agency.db` (gitignored; `--db` to change). A sample report from a real run is in
[`reports/health-sample.md`](reports/health-sample.md).

## How it works

| Part | File | Rule it enforces |
|---|---|---|
| Roles | `roles.py` | 20 roles; each has its own tool list. Every task is verified by a different role (QA verifies everyone, code review verifies QA). Roles with no playbook yet show as *idle*. |
| Tools | `tools.py` | Each tool has an input schema, a permission class (read / execute / network), a timeout and an approval flag. Commands are fixed argv lists, never a shell. Paths must stay inside the repo; `.env` and `.git/` can't be read. Child processes get no `*KEY/*TOKEN/*SECRET/*PASSWORD` variables. Output is truncated and secrets are redacted before storage. A missing program or credential gives BLOCKED. |
| Store | `store.py` | Lifecycle CREATED → ANALYZING → PLANNED → READY → RUNNING → REVIEWING → VERIFYING → COMPLETED, plus BLOCKED, FAILED, CANCELLED, NEEDS_APPROVAL. Every transition is checked and written to `events`; every tool call to `tool_calls`. |
| Orchestrator | `orchestrator.py` | Plans are rejected before running if a role lacks permission, a step is unknown or the graph has a cycle. Independent tasks run in parallel (`--concurrency`). A task never runs after a dependency failed. ERROR (timeout or crash) retries up to `max_attempts`, while FAIL and BLOCKED don't retry. Each mission has a tool-call budget. Leases let a restarted run pick up tasks a crashed run left RUNNING. |
| Provider | `providers.py` | OpenAI-compatible `/chat/completions` (OmniRoute by default). No key: ProviderUnavailable, task BLOCKED. Bounded retry; token usage recorded when the provider returns it. |
| Dashboard | `dashboard.py` | Read-only, 127.0.0.1, every value read from the store, all text escaped, strict CSP. |

Verdicts in reports: **PASS** (ran, passed, verified), **FAIL** (ran and found a problem, or the evidence
contradicted the claim), **BLOCKED** (couldn't run, with the reason), **NOT TESTED** (not run: cancelled or
waiting for approval).

## Adding to it

- **A playbook step:** add a `Step` to `PLAYBOOKS` in `orchestrator.py`. `test_shipped_playbooks_are_valid`
  fails if the role may not use the tool.
- **A tool:** add it in `Toolbox._build()` with a schema, a timeout and an approval flag. Grant it to roles in
  `roles.py`. Add a test that it returns BLOCKED when its program or credential is missing.
- **Anything that changes files, deploys or spends money** must set `requires_approval=True`.
