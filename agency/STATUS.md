# Engineering agency status — stage 2

Verified on 2026-10-24 in the cloud dev container (Linux x86_64, Python 3.13.17; tests also on 3.12).
Nothing here is described as production-ready.

## What exists

| Capability | Where | Approval needed |
|---|---|---|
| 20 roles with separate tool permissions and file ownership | `roles.py` | — |
| 20 tools with schemas, timeouts, redaction, no shell tool | `tools.py` | per tool |
| Persistent missions, tasks, events, audit log, heartbeats; schema migration | `store.py` | — |
| Task graph, parallel runs, bounded retries, budget, lease recovery, cancel that kills | `orchestrator.py` | — |
| Independent verification from the audit log; git re-checks branch claims | `orchestrator.check_evidence` | — |
| Code changes: LLM or human diff → `agency/<branch>` in its own worktree → tests on that branch | playbooks `change`, `patch` | send code, commit |
| Push a reviewed branch | playbook `ship` | push |
| LLM planner (plan only from registered roles/tools; validated; bounded re-ask) | `planner.py`, `ask` | whole plan |
| Health endpoints (allowlist only) | playbook `deploy-check`, `agency.json` | — |
| MCP client over stdio (allowlist only) | `mcp.py`, playbook `mcp-check` | each `mcp_call` |
| Security: secret scan, pip-audit (bot + APEX), bandit | playbook `health` | — |
| Performance timings, PyPI research | playbooks `perf`, `research` | — |
| Token usage and cost (provider-reported tokens; cost only with a configured price) | `report.usage` | — |
| Dashboard: read-only by default; `--actions` adds CSRF-protected buttons | `dashboard.py` | — |
| Worker loop and a daily scheduled run on GitHub | `worker.py`, `.github/workflows/agency-nightly.yml` | never approves |
| Session autopilot: background worker, one per session, health now then hourly | `scripts/agency-live.sh` | never approves |

## Quality gates

| Gate | Result | Evidence |
|---|---|---|
| Existing functionality intact | **PASS** | `tests/` 141 passed (96 original + 45 agency). APEX 86 passed / 2 skipped, unchanged. |
| `run health` on this repo | **PASS** | 12/12 PASS: deps ×2, compile, both test suites, ruff, shellcheck, secret scan, pip-audit ×2, bandit, git. |
| Intentionally failing checks reported as FAIL | **PASS** | Failing test, planted key (stage 1); a patch that breaks a test fails on its branch while main still passes (`test_tests_run_against_the_branch_not_main`). |
| Code change end to end on the real repo | **PASS** | `run patch` (docs role, README diff): waited for approval → committed `agency/doc-env-note` in a worktree → 119 + 86 tests on that branch PASS → main untouched. The demo branch was deleted afterwards. |
| File ownership and protected paths | **PASS** | `test_ownership_and_protected_paths`: backend can't touch README; nobody can touch `.github/`, `agency/roles.py`, `agency/tools.py`. |
| Push needs approval | **PASS** | `test_push_needs_approval_and_reaches_remote` (local bare remote; nothing pushed before approve). |
| LLM-written plans can't run unapproved | **PASS** | `test_planner_plan_waits_for_approval_then_runs`; a rejected plan is fed back once, then the planner gives up (`..._gives_up_after_two_bad_plans`). |
| Cancel kills running work | **PASS** | `test_cancel_kills_a_running_subprocess` (60 s test killed within seconds, call audited); timeouts kill the process group. |
| Health URLs and MCP are allowlisted | **PASS** | Metadata-IP URL refused; empty allowlist reaches nothing. Live: `mcp-check headroom` listed 3 real tools; `deploy-check` PASS on the running dashboard, FAIL on a stopped one. |
| Dashboard actions are protected | **PASS** | `test_dashboard_actions_require_csrf_and_local_host` (no token, wrong token and foreign Host → 403); read-only mode refuses POST. Live: Run button at 390 px. |
| Worker never approves | **PASS** | `test_worker_resumes_approved_work_and_never_approves`. |
| Session autopilot | **PASS** | `test_live_script_starts_one_worker_and_stops_it` (second `start` reuses the worker; `stop` shuts it down cleanly). Live on 2026-10-28: `agency-live.sh start` returned in ~1 s, and the worker ran `health` by itself: 12/12 PASS (145 + 90 tests). |
| Session autopilot starts automatically | **NOT TESTED** | Needs `agency-live.sh start` in the SessionStart hook in `.claude/settings.json`; that change waits for the owner's OK. |
| Usage and cost | **PASS** | Token sums and cost with a configured price (`test_planner_plan_waits...`). No price configured → "cost unknown", never a guess. |
| Old databases keep working | **PASS** | `test_old_database_is_migrated`. |
| Lint, types, SAST | **PASS** | `ruff check agency`, `mypy agency` clean; bandit -ll clean after triage (7 findings reviewed: SQL identifiers from code with bound values, URLs from owner config or fixed pypi.org; the provider now refuses non-http(s) URLs). |
| Real-world checks | **PASS** | pip-audit queried the live advisory DB; `research` read live PyPI (`python-telegram-bot 22.8`). |
| CI on GitHub | **NOT TESTED** | Checked on the PR, not here. |
| LLM paths against a real provider | **NOT TESTED** | `change`, `review`, `ask` verified with stub providers only; the owner's OmniRoute is on their phone. |
| Nightly workflow | **NOT TESTED** | First scheduled run happens after merge (or via "Run workflow"). |
| Deployment / rollback | **NOT TESTED** | There is no deployment target; `deploy-check` covers health URLs you list in `agency.json`. |

## Known limits

- History lives in `agency/out/agency.db`, which is gitignored, so each cloud session starts empty. The nightly
  run keeps its report as a workflow artifact.
- The worker runs while a session or host process keeps it running (`scripts/agency-live.sh start` in a
  session). The only always-on part is the GitHub schedule.
- Roles are permissions and verification duties, not separate AI personalities. LLM work happens only in
  `propose_patch`, `llm_review` and the planner.
