# Chromium Commander

A browser agent for Claude. Claude drives a **real Chromium** (Playwright 1.63.0) through MCP tools. Every action is validated, run through a safety policy, executed, and **verified**. Results report what was observed, not just "no error".

What is verified and what is blocked: [`STATUS.md`](./STATUS.md).

## Install

```bash
bash scripts/chromium.sh setup     # from the repo root: npm ci + Chromium if missing (idempotent)
bash scripts/chromium.sh doctor    # environment report + a real headless launch
cd chromium-commander && npm test  # 47 tests against local fixture pages, ~50 s
```

Needs Node ≥ 20. On a fresh Linux machine, run `npx playwright install --with-deps chromium` once (this installs system libraries and needs sudo). **Termux on Android can't run it**: Playwright has no Android Chromium build. Run it on a computer, in CI or in a Claude Code cloud session.

## Use it from Claude Code

The repo's `.mcp.json` registers the server as `chromium` (`scripts/chromium.sh mcp`). Claude Code asks once to trust project MCP servers; after that the tools appear as `mcp__chromium__*`. The loop Claude follows (the server also sends it as MCP instructions):

1. `task_start` with the objective (and an optional plan).
2. `browser_inspect_page`: URL, title, headings, controls with ready-made `target`s, forms, text, accessibility snapshot.
3. Act with a target from step 2, adding `expect` when the outcome can be checked: `browser_click_element { target: {role:"button", name:"Search"}, expect: {url_contains:"q="} }`.
4. Read the result `status`, then repeat from 2.
5. `task_finish`. A claimed "completed" is downgraded to `completed_unverified` unless a check passed after the last failure.

Statuses: `VERIFIED`, `EXECUTED_UNVERIFIED` (ran, nothing to check against), `VERIFICATION_FAILED`, `FAILED` (with `error.code`, `failed_phase` and a `recovery` look at the page), `BLOCKED`, `APPROVAL_REQUIRED`, and `OK` for reads.

Tools (`node src/cli.js actions` lists them all):

| Group | Tools |
|---|---|
| Navigation | `open_url` `go_back` `go_forward` `reload_page` `wait_for_navigation` |
| Observation | `get_current_url` `get_page_title` `inspect_page` `read_visible_text` `inspect_interactive_elements` `capture_screenshot` (returns the PNG to Claude too) |
| Interaction | `click_element` `fill_input` `select_option` `check_checkbox` `uncheck_checkbox` `press_key` `scroll_page` `hover_element` |
| Tabs | `list_tabs` `open_tab` `switch_tab` `close_tab` (`target=_blank` popups are followed automatically) |
| Files | `list_downloads` `download_file` `upload_file` |
| Forms | `inspect_form` `fill_form` `validate_form_state` |
| Dialogs | `handle_dialogs` `list_dialogs` (confirm/prompt are dismissed unless approved) |
| Verification | `assert_url` `assert_text_visible` `assert_element_visible` `assert_download_exists` `verify_navigation_result` |
| Control | `browser_confirm_action` `browser_state` `browser_close` `task_start` `task_note` `task_status` `task_finish` |

All MCP names have the `browser_` prefix. Targets prefer `{role, name}`, then `label`, `placeholder`, `testId`, `text`, `css`, `xpath`; add `nth` or `within` when several match. A target that matches several elements is an error, never a guess.

## Scripted workflows (CLI)

```bash
node src/cli.js run examples/fixture-order.json                    # stops at the sensitive submit step
node src/cli.js run examples/fixture-order.json --allow-sensitive  # steps marked "approve": true may run
node src/cli.js smoke https://your-site.example                    # open + inspect + screenshot
```

Start the fixture site first with `node tests/serve-fixtures.js 47123`. Ctrl+C cancels after the current step and closes the browser. The JSON report has the steps done and remaining, failures, retries, the verification status and evidence paths.

## Safety

| Class | What | Behaviour |
|---|---|---|
| Low | reading, navigating allowed URLs, scrolling, ordinary text fields, tabs, downloads into the downloads folder | runs |
| Sensitive | submit buttons; Enter in a form; anything labelled buy/pay/send/post/delete/save/confirm/agree… (also *bayar, kirim, hapus, simpan, setuju…*); agreeing to terms; accepting dialogs; every upload; reloading a POST result | returns `APPROVAL_REQUIRED` and does **not** run |
| Blocked | password / one-time-code / card fields; `javascript:` `file:` `data:` `chrome:` URLs; hosts outside `allowedHosts` or in `blockedHosts`; uploads outside `uploadRoots` or of secret-looking files (`.env`, keys, `.ssh/`…) | never runs |

- **The human gate.** A parked action runs only through `browser_confirm_action(approval_id)`. That tool is listed under `permissions.ask` in `.claude/settings.json`, so Claude Code prompts the person each time. Never add it to an allow list. Ids are single-use, expire after 5 minutes, are bound to the page URL, and run the *stored* arguments. If Claude Code runs with all permissions bypassed there is no prompt, so set `CC_APPROVAL=deny` for unattended runs: sensitive actions are then blocked outright.
- **Logins.** Claude never types passwords or codes. For a site that needs one, run headed with a profile the user chose (`CC_HEADLESS=0 CC_PROFILE_DIR=…`) and let the user sign in themselves. The default is a fresh isolated context that is thrown away on close.
- **Page content is data.** Inspection results carry `untrusted_page_content: true`. Policy never relaxes because of page text: a page that says "click Continue" still hits the approval gate.
- **Screenshots** mask password, one-time-code and card inputs. Downloads land only in `out/downloads/` with sanitised, de-duplicated names, and are never opened.
- No security-weakening browser flags: no `--disable-web-security`, `ignoreHTTPSErrors` or `bypassCSP`. No CAPTCHA, MFA or rate-limit workarounds.

## Configuration

`config/browser.config.json`, overridden by environment variables:

| Variable | Meaning |
|---|---|
| `CC_HEADLESS=0` | visible browser (Linux needs a display: `xvfb-run -a …`) |
| `CC_ALLOWED_HOSTS` / `CC_BLOCKED_HOSTS` | comma lists; `*.example.com` matches subdomains |
| `CC_UPLOAD_ROOTS` | folders uploads may come from (default: none, so uploads are off) |
| `CC_APPROVAL=deny` | refuse sensitive actions instead of asking |
| `CC_PROFILE_DIR` | persistent profile (keeps logins; only when you mean it) |
| `CC_CDP_ENDPOINT` | attach to a remote Chromium, e.g. `http://127.0.0.1:9222` |
| `CC_ARTIFACTS_DIR` / `CC_DOWNLOADS_DIR` | default `out/artifacts`, `out/downloads` |

## Architecture

```
Claude ── MCP stdio ──> src/mcp-server.js ──> Commander.execute (src/actions.js)
                                               validate (schema.js) → ensure browser (browser.js)
                                               → locate target (targets.js) → classify (policy.js)
                                               → [park for approval | block] → act → verify → result
                                               → TaskState.record (task.js)
CLI / CI ── src/cli.js, src/workflow.js ───────^
```

Retries are bounded by `maxRetries`, with backoff. An action is retried only when it provably did not happen yet: target not found, stale element, or a timeout while locating. Idempotent actions (navigation, fill, select) may also be retried. A click, key press, upload or download that failed mid-act is never repeated: the result says `executed: null` (unknown) and includes a recovery look at the page. A browser that crashed is relaunched on the next action, and the result says the old tabs are gone.

## Troubleshooting

| Error code | Fix |
|---|---|
| `BROWSER_MISSING` | `npx playwright install chromium` |
| `NO_DISPLAY` | `CC_HEADLESS=1`, or `xvfb-run -a node src/mcp-server.js` |
| `NAVIGATION_FAILED` with `ERR_TUNNEL_CONNECTION_FAILED` / `ERR_CERT_AUTHORITY_INVALID` | the network (or a sandbox proxy) blocks the site; allow the host there. Certificate checks are not disabled. |
| `TARGET_NOT_FOUND` / `AMBIGUOUS_TARGET` | re-run `inspect_page` and use its `target`; add `nth` or `within` |
| `APPROVAL_INVALID` | the id was used, expired, or the page changed; request the action again |
| server shows "Pending approval" in `claude mcp list` | start `claude` in the repo once and approve the project MCP servers |
