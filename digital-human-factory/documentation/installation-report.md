# Installation report

Recorded 2026-11-12 in the Claude Code cloud session. Every line was run here.

| Item | Result |
|---|---|
| OS / arch | Linux x86_64 (cloud container) |
| Python | 3.13.18 (`/usr/local/bin/python3`); project venv `.venv` made with uv |
| Package managers | uv, poetry, pip available; uv used |
| Node.js / npm | 22.23.4 / 10.9.9 (only for the Higgsfield CLI) |
| Git | 2.43.0 |
| Claude Code | 2.1.322 |
| GPU | **none** (`nvidia-smi` not found) → LivePortrait / SadTalker not installed |
| FFmpeg | 6.1.1 with libx264 and AAC |
| Disk | 24 GB free |
| Provider credentials in the environment | **none** (HEYGEN, ELEVENLABS, RUNWAYML, DID, SYNTHESIA all unset) |
| Network to provider APIs | **blocked**: api.heygen.com, api.elevenlabs.io, api.dev.runwayml.com, api.d-id.com, api.synthesia.io, Kling, platform.higgsfield.ai all refused by this sandbox's egress proxy (HTTP 403 on CONNECT). PyPI and npm are reachable. |
| Existing integrations | Higgsfield CLI 1.2.2 installed, not signed in; Higgsfield and ElevenLabs connectors exist in the Claude account (usable by Claude in chat, not by this Python package) |

## Installed

```
dhfactory 1.0.0 (editable, src/dhfactory)
elevenlabs 2.78.0   official SDK, repository github.com/elevenlabs/elevenlabs-python
runwayml 5.27.0     official SDK, repository github.com/runwayml/sdk-python
httpx 0.28.1, pydantic 2.14, pydantic-settings 2.16, pytest 9.2, ruff 0.17
```

Not installed, on purpose: PyPI `heygen` (0.0.0) and `synthesia` (0.2.1) are not published by those companies;
LivePortrait / SadTalker (no GPU; model licences need a deliberate review); any Kling SDK (only unofficial wrappers).

## Verification

| Check | Status | Evidence |
|---|---|---|
| `import dhfactory` | PASS | path `src/dhfactory/__init__.py` |
| `dhfactory --help`, `doctor` | PASS | doctor lists 8 providers and 7 agents |
| Agents importable, named, described | PASS | `tests/test_pipeline.py::test_agents_have_names_and_descriptions` |
| Missing credentials → ProviderNotConfigured (BLOCKED), never a fake success | PASS | `test_every_paid_provider_refuses_without_credentials`, doctor output |
| Adapters against mocked HTTP / fake SDKs | PASS | `tests/test_providers.py` (HeyGen, D-ID, Synthesia, ElevenLabs timings, Runway, key never sent to file host) |
| Spend gate | PASS | `test_paid_step_blocked_without_approval_independent_steps_continue`, `test_cost_guard_rules` |
| Resume without re-running or re-paying | PASS | `test_dry_run_..._resumes`, `test_paid_job_id_is_reused_on_resume` |
| Full 14-step dry run (mock provider) | PASS | `rendered-videos/demo-presenter/final.mp4`, 1080×1920, 10.10 s, h264 + AAC 48 kHz, −14.0 LUFS, full decode clean; QC overall **BLOCKED** because it is a labelled mock |
| `pytest -q` | PASS | 21 passed |
| `ruff check src tests` | PASS | All checks passed |
| Live provider call | **BLOCKED** | no credentials, and provider hosts unreachable from this sandbox |
| Real presenter video | **BLOCKED** | see `test-reports/demo-status.md` |
