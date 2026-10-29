# HALLMARK: Human Design Agent

A Claude Code skill and subagent for human-centered product design. It turns a human need into a working UI that is accessible and responsive, and it checks the result with real tools before calling anything done. Claude's instructions live in [`SKILL.md`](./SKILL.md). This file is for people.

Status words: **VERIFIED** ran and passed · **IMPLEMENTED** built, not fully checked · **NOT RUN** not checked (reason given).

## What's installed

| Path | Purpose |
|---|---|
| `.claude/skills/hallmark/SKILL.md` | The workflow: Observe → Understand → Define → Explore → Design → Implement → Verify → Report, plus the rules |
| `reference/accessibility.md` | WCAG 2.2 AA checklist, each item tagged tool-checkable or human-only |
| `reference/ui-system.md` | Hierarchy, type, spacing, color roles, tokens, component states, anti-patterns, product-type notes |
| `reference/research-and-strategy.md` | Strategy questions, jobs to be done, research methods, usability test plan, heuristic review |
| `reference/ai-interaction.md` | Human-AI interaction: expectations, uncertainty, control, failure states, privacy |
| `templates/design-contract.md` | The design contract to fill before building |
| `scripts/hallmark_check.py` | Checker: `check` (static), `contrast`, `render` (stdlib Python) |
| `scripts/render_check.cjs` | Chromium render at 390/768/1440 px through Node Playwright (called by `render`) |
| `.claude/agents/hallmark.md` | Subagent that runs the workflow in its own context and returns a status report |
| `tests/test_hallmark.py` | Tests for the checker and the install (run in CI with the rest of `tests/`) |

## How to use it

- **Ask in plain words.** Claude loads the skill when the task is UI design, review or accessibility work, or when you say "HALLMARK".
- **Call it directly:** `/hallmark <task>`, or "use the hallmark agent to …" to run it as a subagent.
- **Run the checker yourself:**
  ```
  python3 .claude/skills/hallmark/scripts/hallmark_check.py check page.html          # 0 = pass, 1 = errors
  python3 .claude/skills/hallmark/scripts/hallmark_check.py contrast '#767676' '#fff'
  python3 .claude/skills/hallmark/scripts/hallmark_check.py render page.html --out shots/
  ```
  `--strict` makes warnings fail too, and `--json` gives machine-readable output. `render` exits 3 (**BLOCKED**) when Node, Playwright or Chromium is missing. It never reports a pass it didn't earn.

## Checks

| Static (`check`) | Rendered (`render`) |
|---|---|
| `DOC-LANG` `DOC-TITLE` `DOC-VIEWPORT` `DOC-ZOOM` `LANDMARK-MAIN` `ID-DUP` `IMG-ALT` `CTRL-NAME` `FORM-LABEL` `FAKE-BUTTON` `LINK-DEAD` `ARIA-HIDDEN-FOCUS` `TABINDEX-POSITIVE` `HEADING-SKIP` `HEADING-H1` `FOCUS-HIDDEN` `MOTION` `TEXT-TINY` `CONTRAST` | Sideways scroll per viewport · console and page errors (incl. broken images) · every Tab stop must look different when focused (outline/shadow, or a pixel comparison against an unfocused baseline) · full-page screenshots |

Contrast reads CSS rules that set both `color` and `background(-color)`, and resolves `var(--token)` to the token's **first** definition. Dark-theme values need a separate `contrast` call.

## Adding to it

- **New rule:** add it in `check_html()` with a rule ID, then add one row to `test_each_rule_fires_on_its_defect` with the defect that should trigger it.
- **New discipline** (e.g. motion design, localisation): add `reference/<topic>.md` and one row in SKILL.md's "When / Read" table. Use a separate skill only when it should trigger on its own.
- **Visual specifics for one product:** put them in that product's own skill (like `done-protocol`). Project skills win over HALLMARK's defaults.

## Optional integrations

Nothing below is required, and nothing was installed for HALLMARK.

| Integration | Use | State |
|---|---|---|
| Chromium + Playwright (Node) | `render` | Preinstalled in cloud sessions. On another machine: `npm i -g playwright && npx playwright install chromium`. |
| `frontend-design` skill | Aesthetic direction | Installed (`.claude/skills/frontend-design`). |
| Figma connector (claude.ai) | Read designs, push code to Figma | Shows up in sessions where the owner connected it. Not used or tested by HALLMARK. |
| axe-core, Lighthouse | Deeper automated audits | Not installed. Add one only if a project needs it, and record it here first. |

## Security

- The checker reads local files and makes no network calls. `render` loads only the file or URL you give it, in a headless browser.
- The subagent can't deploy, publish, spend money, install MCP servers or upload files. It returns those steps as next actions for the owner.
- No secrets are needed or stored. Nothing was added to `.env.example`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `render` → `BLOCKED: Node package 'playwright' not found` | Install Playwright for Node (see above), or check `node -e "require('playwright')"` |
| `render` → console error `ERR_FILE_NOT_FOUND` | A referenced asset (image, CSS, script) is missing next to the HTML. It's a real defect. |
| A focus finding on a custom widget you believe is fine | Look at the screenshot. If focus really is visible, give it an explicit `:focus-visible` outline so it can't regress. |
| Skill not offered in a session | It must be at `.claude/skills/hallmark/SKILL.md`. Check that `python3 .claude/skills/skills-manager/scripts/skills_manager.py list` shows `hallmark`. |

## Known limits

- Automated checks cover a subset of WCAG. They can't judge alt-text quality, plain language, reading order, screen-reader output or cognitive load. SKILL.md makes the agent list those items as NOT RUN.
- The static parser checks one HTML file. JS-rendered UIs (React etc.) need `render` on the running app.
- HALLMARK doesn't learn between sessions. Improvements happen by editing these files.
- There is no user research. HALLMARK frames hypotheses and writes test plans; real users have to run them.

## Verification log

See [`STATUS.md`](./STATUS.md).
