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
| `bash scripts/agency-live.sh start` / `status` / `stop` | Autopilot for a session: starts the worker in the background (health now, then hourly; resumes approved work), only if none is running. `status` lists the latest missions and anything waiting for approval. Pid and log in `agency/out/`. `AGENCY_LIVE_PLAYBOOK` / `AGENCY_LIVE_EVERY` change the schedule |
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

## OVERLORD: production departments, self-healing, film-editor queue

The same orchestrator now runs the repository's production programs. It does not reimplement them: each department's
tool calls an existing project's own program in that project's own environment, and the result is verified by a
different role (QA re-probes any media file a task claims to have produced).

| Department role | Tool | Runs | Output |
|---|---|---|---|
| `humanverse` | `build_character` | HUMANVERSE `build_character.py` (Blender) | rigged 3D human: geometry, skeleton, skin weights, facial rig, deformation test, GLB/FBX |
| `audio` | `voice_dialogue` | AURAVOX `avx produce` + `avx work` | takes, QA, retries, master (−16 LUFS), lip-sync data |
| `video` | `talking_scene` | `auravox/demo/gate4/gate4.py` → HUMANVERSE `build_scene.py` + `render.py` | lip-synced Cycles render muxed to MP4 |
| `video` | `cartoon_episode` | Cartoon Studio `run` + `qc` (13-step resumable editor: storyboard, voices, animation, mix, assembly, 25-check QC, export) | `cartoon-studio/rendered-videos/<job>/final.mp4` |
| `technical`, `qa` | `integration_probe`, `media_verify`, `project_tests` | real work per integration; ffprobe + full decode + black/silence detection; each project's tests | evidence with VERIFIED / FAILED / BLOCKED / NOT INSTALLED |

| Command | What it does |
|---|---|
| `run integrations` | Proves 14 integrations by doing work (render a frame, encode/decode, speak and measure, free read-only API call with an existing key) |
| `run digital-human --param character=CHAR-HUM-003 --param screenplay=FILE --param name=ID` | Build → voice → lip-synced render → verified MP4, into `agency/out/production/<ID>/` |
| `run cartoon --param job=ep003 --param universe=U --param episode=E` | Cartoon Studio episode + independent MP4 verification |
| `run production-tests` | Every production project's test suite in its own venv |
| `agents` | The 37 named agents, their department, the role/tool that really does the work, and live state from the audit log |
| `heal` / `diagnose` | One self-healing pass / failure categories and the recovery log |
| `dashboard` | Now the OVERLORD Command Center: system status, integrations, MCP, production outputs, agents, error log, recovery history |

**Self-healing** (`healing.py`, run by the worker every loop): watchdog re-queues tasks whose runner died (expired
lease) and reports stalled workers; a classifier sorts each non-passing task into transient, missing_dependency,
credential, approval, budget, dependency, check_failed or unknown; transient and missing-dependency failures are
retried at most 3 times with exponential backoff (60 s / 600 s base); a FAIL verdict, a missing credential or an
approval is never retried and is escalated once with what a person must do; the same step failing in 3 missions in a
week is escalated as recurring. Every action is a row in `recoveries`.

**Assets are never overwritten by two agents**: production tools write under `agency/out/production/<name>/` with an
exclusive per-asset lock (a live holder → BLOCKED; a stale lock from a dead process is taken over so a retry resumes),
and AURAVOX refuses to produce over an existing master.

**Film-editor skill** (`.claude/skills/overlord-autonomous-film-editor/`, installed with `avx skills install`, scanned,
host-tested): its queue maps onto this store. PENDING = READY mission, VALIDATING/INGESTING/EDITING/AUDIO/SUBTITLES/
RENDERING = Cartoon Studio steps 01–13 inside the `episode` task (its own state file checkpoints each step),
QC = studio QC + OVERLORD `media_verify`, RETRY_WAIT = a scheduled self-healing retry, REWORK = a human `retry` after a
fix, BLOCKED / FAILED / CANCELLED = the same states here. Atomic claiming, leases, crash recovery, bounded retries,
per-tool timeouts and the audit log are the store's.
