# Engineering agency status — stage 1

Verified on 2026-10-24 in the cloud dev container (Linux x86_64, Python 3.13.17; tests also on 3.12).
Nothing here is described as production-ready.

## Quality gates

| Gate | Result | Evidence |
|---|---|---|
| Existing functionality intact | **PASS** | Baseline before changes: `tests/` 96 passed, APEX 86 passed / 2 skipped. After: `tests/` 119 passed (96 + 23 new), APEX unchanged. |
| Roles registered and callable | **PASS** | `python -m agency roles`. `test_roles_are_distinct_and_tools_exist`. |
| Task orchestration works end to end | **PASS** | `run health` on this repo: 10/10 PASS, exit 0 ([sample](reports/health-sample.md)). Repeated in a fresh `git clone` + new venv: 10/10 PASS. |
| An intentionally failing test is reported as FAIL | **PASS** | `test_passing_and_intentionally_failing_tests_are_reported_honestly`. Live: a fake key committed in a throwaway clone gave `secrets` **FAIL**, mission FAILED, exit 1, key not printed. |
| Missing tools are BLOCKED, not PASS | **PASS** | First live run: shellcheck and pip-audit absent → both BLOCKED, mission BLOCKED, exit 2. After installing them, `retry` + `resume` → PASS (both attempts kept in the audit log). |
| Agent failures can't loop forever | **PASS** | `test_errors_retry_a_bounded_number_of_times` (3 attempts, then FAILED; resume adds no calls), `test_tool_call_budget_blocks_the_rest`, cycle rejection at plan time. Tasks are fixed at plan time, so no agent can create work. |
| Task state survives restart | **PASS** | `test_restart_recovers_a_task_left_running`: a task left RUNNING with an expired lease is re-queued by a new process and completes. |
| Tool permissions enforced | **PASS** | Plan-time rejection (`test_plan_rejects_bad_playbooks`) and call-time `PermissionDenied`, path, `.env` and argument checks (`test_tool_permissions_and_input_boundaries`). |
| Human approval for sensitive actions | **PASS** | `run review` on this repo stops at NEEDS_APPROVAL, with nothing sent. `test_review_needs_approval_then_runs_against_provider`: no request reaches the stub LLM before `approve`; after approval the diff is handed off and token usage recorded. |
| Logs don't expose secrets | **PASS** | `test_output_is_redacted_and_child_env_has_no_secrets`, `test_secret_scan_finds_tracked_credentials`. |
| Dashboard reads real backend state | **PASS** | `test_dashboard_shows_real_state_and_escapes_output` (binds 127.0.0.1, HTML-escapes tool output). Checked at 390 px width: no horizontal page scroll. |
| Lint and type checks | **PASS** | `ruff check agency` (config `agency/ruff.toml`; pinned `ruff==0.17.2` in CI). `mypy agency`: no issues. |
| Security scans executed | **PASS** | secret scan: 0 findings in tracked files. `pip-audit -r requirements.txt`: no known vulnerabilities (live query). APEX requirements are not audited yet. |
| Installation tested in a clean environment | **PASS** | Fresh clone + `python3.13 -m venv` + the README's install line → 10/10 PASS. |
| CI on GitHub | **NOT TESTED** | The workflow gained `ruff check agency`; the branch's CI run result is not checked here. |
| LLM review against a real provider | **NOT TESTED** | Verified against a local stub only. The owner's OmniRoute runs on their phone, not reachable from here. |
| API authentication / authorization | **NOT TESTED** | There is no network API: the dashboard is read-only on 127.0.0.1, and actions are CLI-only. |
| Deployment health, rollback | **NOT TESTED** | No deployment target or credentials. |

## NOT IMPLEMENTED (next stages, in priority order)

1. **Agents that change code.** There is no file-edit tool yet, so file ownership and branch isolation aren't
   enforced. The next step is a `propose_patch` tool: the patch goes to a branch, is shown for approval, then
   checked by `health`.
2. **LLM planning.** Playbooks are fixed. A model-proposed plan would go through `validate_playbook` before
   anything runs.
3. **Dashboard actions** (run / approve / cancel / retry) with a CSRF token. They're CLI-only today.
4. **Kill on cancel.** A cancelled mission stops new work, but a subprocess already running finishes (bounded by
   its timeout).
5. **APEX dependency audit, bandit, container scan.** Only the bot's requirements are audited.
6. **MCP client, deployment checks, cost tracking beyond provider-reported tokens.**
7. **24/7 worker.** Missions run when invoked. Nothing schedules or supervises them.
