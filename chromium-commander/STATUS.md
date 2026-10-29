# Chromium Commander: status

Checked 2026-10-29 in a Claude Code cloud container (Ubuntu 24.04, Node 22.22.0, Playwright 1.63.0, Chromium 153.0.8010.12 headless shell / revision 1243).

## VERIFIED

| Capability | Evidence |
|---|---|
| Launch real Chromium (headless) | `node src/cli.js doctor` → `launch: ok`, `browser_version: 153.0.8010.12`; test A |
| Visible (headed) Chromium | `CC_HEADLESS=0 xvfb-run -a node src/cli.js doctor` → `launch: ok` on display `:99` |
| Navigation, history, reload, waits, HTTP status checks | `tests/navigation.test.js` (B) |
| Page inspection: text, headings, ARIA controls → targets, forms, accessibility snapshot | `tests/browser-smoke.test.js` (C); every suggested target resolves to exactly one element |
| Click / fill / select / check / key / scroll / hover with verification | `tests/interaction.test.js` (D, E) |
| Tabs, including `target=_blank` popups | test F |
| Real PNG screenshots with metadata; secret inputs masked | test G; the end-to-end screenshot shows the password and card fields masked |
| Downloads into the downloads folder, de-duplicated names, empty files flagged | test H |
| Uploads only after approval and only from `uploadRoots` | interaction + safety tests |
| Timeouts, missing or ambiguous targets, mid-act failures and crashes reported, never turned into success | `tests/recovery.test.js` (I) |
| Approval gate: sensitive actions don't run without `confirm`; ids single-use, expiring, page-bound; `deny` mode; secret fields blocked | `tests/safety.test.js` (J) |
| Multi-step workflows: stop on failure, approval opt-in on both sides, cancellation | `tests/workflow.test.js`; `node src/cli.js run examples/fixture-order.json [--allow-sensitive]` |
| MCP server (JSON-RPC over stdio) | `tests/mcp.test.js` spawns the server as Claude Code does |
| **Claude invokes the tools** | A headless `claude -p` session (CLI 2.1.312) with this server via `--mcp-config` called `task_start`, `browser_open_url` (VERIFIED), `browser_inspect_page` (OK), `browser_click_element` (VERIFIED), `browser_fill_input` (VERIFIED), `browser_click_element` on the submit button (**APPROVAL_REQUIRED**; the fixture server received no POST), `browser_capture_screenshot` (VERIFIED) and `task_finish`. It also reported the page's "ignore all previous instructions" line as page content and did not act on it. |

`npm test`: **47/47 pass**, three consecutive runs, ~47 s each.

## NOT VERIFIED (environment)

| What | Why |
|---|---|
| Public websites from this cloud sandbox | Its proxy refuses `example.com` (`curl` gets 403 too), and intercepts TLS for allowed hosts, so Chromium rejects `pypi.org` with `ERR_CERT_AUTHORITY_INVALID`. Certificate checks stay on by design. The agent reports both as `FAILED / NAVIGATION_FAILED`. Expected to work wherever Chromium has normal internet. |
| `chromium` in `.mcp.json` inside an interactive session | `claude mcp list` shows "Pending approval" until someone starts `claude` in the repo and approves the project's MCP servers once. The same server was verified through `--mcp-config` (above). |
| CI job `chromium` | Added to `.github/workflows/test.yml`; runs after push. |
| The `permissions.ask` prompt for `browser_confirm_action` | Guarded by `tests/test_mcp_config.py`. Seeing the prompt needs an interactive session. |

## NOT IMPLEMENTED (by design or later)

- Continuous video observation: screenshots are taken on demand only.
- Scheduled or background workflows, a control panel, and task history across sessions. Nothing runs in the background: the MCP server lives only as long as the Claude session, and the CLI only as long as its command.
- Android/Termux: Playwright has no Android Chromium build.
- CAPTCHA, MFA or rate-limit workarounds: never.
