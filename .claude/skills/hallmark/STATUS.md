# HALLMARK: status

Status words: **VERIFIED** ran and passed · **IMPLEMENTED** built, not fully checked · **NOT RUN** not checked (reason) · **NOT IMPLEMENTED**.
Built and verified 2026-10-29 in a claude.ai cloud session: Claude Code 2.1.312, Ubuntu x86_64, Python 3.13.17, Node 22.22.0, Node Playwright + Chromium (preinstalled).

## Install

| Item | State | Evidence |
|---|---|---|
| Skill at `.claude/skills/hallmark/` | VERIFIED | `skills_manager.py list` → `hallmark [installed: project]`; `doctor --offline --brief` → all checks PASS |
| Skill discovered by Claude Code | VERIFIED | Fresh `claude -p … --output-format stream-json --verbose` in the repo: the `system/init` event lists `hallmark` in `skills`. It also appeared live in the building session without a restart. |
| Subagent `.claude/agents/hallmark.md` discovered | VERIFIED | Same init event lists `hallmark` in `agents` (23 agents). HarnessFlow's `cli_setup.sh` only writes its own files, so this hand-written file is left alone and the CI drift check stays clean. |
| Subagent runs a real task end to end | VERIFIED | Headless `claude -p` asked for a wedding-RSVP page via the `hallmark` subagent (132 s). It read SKILL.md and the references, chose colors with `contrast`, built the page, ran `check --strict` (0/0) and `render` (first run FAILED: radio buttons had no focus ring; it fixed the CSS and re-ran to PASS), wrote and ran a 24-step keyboard/journey test, opened its screenshots, listed its assumptions, flagged that "sudah kami terima" overstates a page with no backend, and named the human-only checks as NOT RUN. Independent re-check of its page: `check` 0 errors, `render` PASS, overflow 0 at all widths. Repo `git status` clean afterwards. |
| No secrets in new files | VERIFIED | Pattern scan of the skill, agent and test: 0 matches. No `.env` changes; none needed. |

## Checker (`scripts/hallmark_check.py`)

| Feature | State | Evidence |
|---|---|---|
| 19 static rules (see README) | VERIFIED | `tests/test_hallmark.py`: a clean page has 0 findings, and each rule fires on its own injected defect (22 parametrized cases) |
| Accessible-name logic (aria-label, wrapping label, `img alt` inside link, `role`+`tabindex`) | VERIFIED | unit tests |
| Contrast (WCAG formula, `var(--token)` resolution, error < 3:1, warn < 4.5:1) | VERIFIED | reference values 21:1, 1:1, `#767676`/white = 4.54:1 |
| CLI exit codes 0/1/2, `--strict`, `--json` | VERIFIED | unit tests |
| `render`: sideways scroll, console errors, screenshots ×3 | VERIFIED | real Chromium test: clean page PASS with 3 PNGs; `body{width:1200px}` → FAIL "scrolls sideways" |
| `render`: focus visibility | VERIFIED | `button{outline:none}` flagged at all 3 widths, including desktop where a link sits next to the button. Native `<input type="date">` (ring drawn in shadow DOM) is not flagged. Two earlier versions got these wrong and were fixed: style-only check (date input false positive), then neighbour-ring leak (missed the button at desktop). |
| `render` without Node/Playwright → BLOCKED, never PASS | VERIFIED | unit test (monkeypatched `which`) |
| Chromium test in GitHub CI | NOT RUN | CI's `check` job has no Node Playwright; the test skips there with a reason. The static and CLI tests run in CI. |
| Full repo suite after the change | VERIFIED | `.venv/bin/python -m pytest -q tests` → 187 passed |

## Not covered (needs a human or a future tool)

Screen-reader output, alt-text quality, plain language, reading order, 200% zoom and text-spacing reflow, non-text contrast, JS-rendered apps (run `render` on the running app instead of `check` on source), real-user usability. SKILL.md makes the agent report these as NOT RUN.
