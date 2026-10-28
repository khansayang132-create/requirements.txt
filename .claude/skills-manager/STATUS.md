# Skills manager: status

How to use it: [`../skills/skills-manager/SKILL.md`](../skills/skills-manager/SKILL.md) (`/skills-manager <command>` in Claude Code, or `python3 .claude/skills/skills-manager/scripts/skills_manager.py <command>`).
Status words: **PASS** checked and passed · **FAIL** checked and failed · **BLOCKED** couldn't be checked · **NOT RUN** not checked.
Last updated 2026-10-28 (Claude Code 2.1.312, Ubuntu 24.04 x86_64, Python 3.13.17, git 2.x). Built 2026-10-23; re-verified from scratch 2026-10-28 (see *Re-verification*).

## Environment it was built against

| Item | Found |
|---|---|
| Agent | Claude Code CLI 2.1.309 in a claude.ai cloud container. Skills load natively from `.claude/skills/` (project) and `~/.claude/skills/` (user), and claude.ai-synced skills appear as `anthropic-skills:<name>`. New skill folders are picked up live, without a restart. |
| Discovery proof | `claude -p … --output-format stream-json --verbose` emits a `system/init` event whose `skills` array is what Claude Code actually discovered. `verify --live` reads it. |
| Other catalogs | Codex `.agents/skills/` (symlink to done-protocol), HarnessFlow `.github/HarnessFlow/skills/` (workflow-only), MCP server `headroom` in `.mcp.json`. |
| Network | `git` reaches github.com through the proxy. The GitHub REST API answers 403, so remote discovery is git-only. |

## Features

| Feature | State | Evidence |
|---|---|---|
| Discovery: project, user and synced skills, Codex, HarnessFlow, MCP servers | VERIFIED | `list` shows 27 local skills and 1 MCP server in this container |
| Discovery: git sources (`anthropics/skills` official; `obra/superpowers`, `addyosmani/agent-skills` catalogued) | VERIFIED | 76 remote skills found; `doctor`: all 3 sources reachable |
| Natural-language search and recommend (idf-weighted, synonyms, smallest covering set, installed first) | VERIFIED | see *Search spot checks* |
| Frontmatter validation (Agent Skills name and description rules) | VERIFIED | unit tests |
| Static security scan (14 rules plus symlink, binary and secret-exfiltration checks), dependency check | VERIFIED | unit tests with malicious packages; real scan of 76 remote and 20 local skills |
| Atomic install with registry, hashes and history; no code from the skill is run | VERIFIED | unit tests (tripwire script never runs); real install below |
| Policy gates: `--reason`, `--accept-risk` for medium, block on high, `--force` for duplicates, daily cap | VERIFIED | unit tests; mutation test (disabling the block makes 2 tests fail) |
| `verify` (files, hashes, SKILL.md, skill root, source, deps, live discovery, live load) | VERIFIED | real run below |
| `update` (diff, then `--yes`), `remove` (`--yes`, managed only, backup), `rollback` | VERIFIED | unit tests; real remove → rollback below; mutation test on the `--yes` guard |
| Commit pinning per source (`commit` in `config.json`, `pin` command); refresh and update never move a pin | VERIFIED | unit tests; real run: `anthropics-skills` pinned to its parent commit `9d630808` → cache checked it out from GitHub by SHA → pinned back to `dbd4588f` → checked out again. All 3 sources are pinned to their 2026-10-23 HEADs |
| `upgrade`: moves pins and updates installed skills; held when a changed skill scans medium or higher, is invalid, or was removed upstream | VERIFIED | unit tests (upgrade, hold, BLOCKED, skipped); real run 2026-10-23: all 3 sources up to date |
| `audit` (risk, hash drift, duplicates, missing files) → `reports/skills-audit.json` | VERIFIED | real run below |
| `disable` / `enable` (park a managed skill outside the skill root; `update --yes` refuses and `upgrade` holds the source while it's disabled) | VERIFIED | unit tests (files and neighbours unchanged, survives a fresh registry read, remove and rollback while disabled); mutation tests (copy instead of move → 4 failures; no upgrade hold → 1 failure); real run 2026-10-28: init event 43 → 42 → 43 skills, then `--load` PASS |
| Network timeouts reported as BLOCKED, not a crash | VERIFIED | found live 2026-10-28: a 30 s `git ls-remote` timeout crashed `doctor` with a traceback. `git()` now returns exit 124; unit test |
| Autopilot (`autopilot` command + daily workflow `skills-autopilot.yml`; commits only when a pin or managed skill moved, after tests and `doctor`) | IMPLEMENTED; command VERIFIED | unit tests (low-risk upgrade lands and nothing new is installed; a risky upgrade is held and a hand edit is reported, exit 1); mutation tests (ignore held → 1 failure; ignore hand edits → 1 failure); real run 2026-10-28 in a throwaway worktree: PASS, `anthropics-skills` pin `dbd4588f` → `ca45fc49`, no installed skill changed. Workflow: see *Autopilot runs* |
| Session-start health line (`doctor --offline --brief` in `.claude/settings.json`) | VERIFIED | unit test (no network call, one line when healthy, problems listed); run through the hook command: `skills-manager: 29 local skills, 1 managed, all checks PASS` |
| `doctor` | VERIFIED | real run: all PASS |
| Self-improvement record (`--reason` on install, `note` after use) | IMPLEMENTED | history lines exist; the workflow itself is guidance in SKILL.md, not enforced code |
| Codex adapter (install into `.agents/skills/`) | NOT IMPLEMENTED: BLOCKED | no Codex CLI in this container, so Codex discovery can't be checked; left out rather than shipped unverified |
| claude.ai catalog (`SearchSkills`, `SuggestSkills`, `SearchPlugins` agent tools) | NOT IMPLEMENTED in the script | agent tools a script can't call; SKILL.md tells the agent to use them as an extra source |

## Real end-to-end run

Skill: `frontend-design` from `https://github.com/anthropics/skills` @ `dbd4588f9e1033efb41dad4bef2f7947c8993d44` (official, Apache-2.0, 2 files, no scripts).
Why: this session's MCP instructions route web and UI work to a `frontend-design` skill, but none was installed. It also fits LSKhan Studio and APEX dashboard UI work.

| Check (`verify frontend-design --live --load`) | Result |
|---|---|
| files installed | PASS: `.claude/skills/frontend-design` |
| files match registry hashes | PASS: 2 files |
| SKILL.md valid | PASS |
| name matches registry | PASS |
| location is a Claude Code skill root | PASS |
| source exists | PASS: `git ls-remote` HEAD `dbd4588f9e10` |
| dependencies available | PASS: none needed |
| Claude Code discovers it | PASS: present in the `claude -p` init event (43 skills) |
| Claude Code loads it | PASS: Skill tool called with `frontend-design`; reply `# Frontend Design`, the file's real first heading |

Then: `remove` without `--yes` → REFUSED (exit 2). `remove --yes` → deleted, backup kept. `rollback` → restored. `verify --live` → PASS again. Also from the init event: `skills-manager` itself is discovered (PASS). The full trail is in `history.jsonl`.

## Tests

`python -m pytest -q tests` → **151 passed** on 2026-10-28 (62 in `tests/test_skills_manager.py`). Was 96 on 2026-10-23. These are unit and integration tests: sources are real local git repos and HOME is a temp folder. **They don't exercise the live `claude` CLI**; the live checks above do, and CI can't run them (no logged-in CLI there).
GitHub CI on commit `8679b92` (run #97: `check`, `service` ×2, `termux`, `apex`): **PASS**.
Mutation checks: disabling the high-risk block → 2 failures. Disabling the `remove --yes` guard → 1 failure.

## Re-verification (2026-10-28)

Every check below was run again in this session against the real CLI and real GitHub sources, not copied from the earlier run.

| Acceptance test | Result | Evidence |
|---|---|---|
| 1 Discover from trusted sources | PASS | `list --all --refresh`: 59 remote (19 anthropics, 15 obra, 25 addyosmani) + 29 local, no source problems |
| 2 Inspect without executing | PASS | `inspect webapp-testing`: MEDIUM, 2 findings, 4 scripts, `playwright` missing; nothing run |
| 3 Install a safe skill | PASS (dry run) | `install internal-comms --dry-run`: risk none, nothing written. The real install proof is `frontend-design` above; no unneeded skill was added |
| 4–6 Files exist, metadata valid, Claude discovers it | PASS | `verify frontend-design --live --load`: 9/9 PASS, Skill tool returned `# Frontend Design` |
| 7 Routing for a sample task | PASS, with a limit | "debug a failing python test" → `debugging-and-error-recovery`; "security review of a pull request" → `code-review-and-quality` + `security-and-hardening`. "build a website landing page" → an unrelated installed skill first: lexical limit, see below |
| 8 Duplicate install | PASS | `install frontend-design` → REFUSED, exit 2 |
| 9 Invalid skill rejected | PASS | real CLI on a throwaway source: `Bad_Name` without description → REFUSED, nothing written |
| 10 Failed install doesn't corrupt state | PASS | unit test `test_failed_copy_leaves_no_partial_install` |
| 11 Records survive a restart | PASS | each CLI call is a new process reading `registry.json`; the disabled state was read back by later calls |
| 12 Update/remove keep unrelated files | PASS | unit tests check neighbour hashes |
| `doctor --live` | PASS | 13/13, `claude -p` init lists 43 skills |
| `audit` | PASS | high 0 · medium 7 · low 6 · none 16 |

Update available: `anthropics-skills` HEAD moved to `ca45fc49` (no installed skill changes). Left for the first autopilot run to apply, which the owner approved.

## Autopilot runs

NOT RUN yet on GitHub (added 2026-10-28; first run is triggered after merge).

## Security and compatibility report

`audit` over every local skill: high 0 · medium 7 · low 6 · none 16 (the details are in `reports/skills-audit.json`). The medium ones are claude.ai-synced document skills that run scripts and call subprocesses (`docx`, `pptx`, `xlsx`, `google-workspace`, `stratawright-daw`), plus `import-memory` and `skill-creator`. Those two are defensive mentions, downgraded from high, never lower.

Scan of the 76 remote skills (2026-10-23): high 0 · medium 18 · low 11 · none 47. Before the context rule, 6 official or catalogued skills scored high on **defensive** text ("never run `curl | sh`", "can't exfiltrate a vaulted credential", "Do not tell the user they need…"). Each line was read by hand; all six were false positives. Fixes: in docs and code comments, a high match next to a warning word becomes medium, so a human still reviews it. The concealment rule now matches only hiding phrasing. An env-plus-network script is medium only when every host it names is a first-party API (for example `api.anthropic.com`).

Compatibility: every install is recorded as `compatible: ["claude-code"]`. Codex reads `.agents/skills/`. The tool lists that folder but doesn't install into it.

## Known limits and next steps

- The scan is a line-based heuristic. It can't follow obfuscation across lines or files, or see what an allowed network call sends. Treat medium as "read it", not "fine".
- Search is lexical (idf plus a small synonym map). Unrelated installed skills can still appear, even as the first pick, when they share generic words ("page", "build", "web"). Tried 2026-10-28: a `website` synonym made it worse (`done-protocol` first), so it wasn't kept. The agent must read the description before using a hit. Claude Code's own runtime choice is by description and doesn't depend on `recommend`.
- Backups (`backups/`) are gitignored and live in the container, so they vanish with it. The committed registry still records source and commit, so an install can be repeated.
- Pins are commit SHAs, not signatures: they stop silent upstream changes, but they don't prove who wrote a commit. Moving a pin still needs a human review of the diff (`update` lists the changed files).
- Next: a Codex adapter once a Codex CLI is available to verify it.
