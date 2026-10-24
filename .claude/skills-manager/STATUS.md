# Skills manager: status

How to use it: [`../skills/skills-manager/SKILL.md`](../skills/skills-manager/SKILL.md) (`/skills-manager <command>` in Claude Code, or `python3 .claude/skills/skills-manager/scripts/skills_manager.py <command>`).
Status words: **PASS** checked and passed · **FAIL** checked and failed · **BLOCKED** couldn't be checked · **NOT RUN** not checked.
Last updated 2026-10-23 (Claude Code 2.1.309, Ubuntu 24.04 x86_64, Python 3.13.17, git 2.x).

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

## Second install: skill-anything + skill-anything-pro (2026-10-24)

Skill: `skill-anything` from `https://github.com/AgentSkillOS/SkillAnything` @ `0f7d5274` (MIT, community, 49 files, 17 scripts). Added as source `agentskillos-skillanything` (pinned) on the owner's request. Risk **medium**: 8 findings, each read by hand. Subprocess calls use argument lists (`<tool> --help`, `claude -p`, `pyarmor`), urllib GETs only the target the user gives, and the two "runtime install" hits are printed hints. Installed with `--accept-risk`.

| Check (`verify skill-anything --live --load`) | Result |
|---|---|
| files, hashes, SKILL.md, name, skill root, source | PASS |
| dependencies available | FAIL: `scripts` is the skill's own package (false positive); `anthropic` is missing and only Phase 6 needs it |
| Claude Code discovers it | PASS (44 skills; 45 with the pro skill) |
| Claude Code loads it | PASS: reply `# SkillAnything` |

**Upstream bug found:** `scripts/run_eval.py` (Phases 5 and 6) runs `claude -p --output-format stream-json` without `--verbose`, and the CLI refuses that. It also looks for a tool named after the skill instead of `Skill`, and it writes temp files into `~/.claude/commands`. Result: nothing ever counts as triggered. On a 2-positive/2-negative jq set, upstream scored 0 true positives (pass rate 50%, from the negatives alone).

**`skill-anything-pro`** (hand-written, not managed): `trigger_eval.py` runs each query in its own temp project with `--verbose --max-turns 1 --allowedTools Skill`, detects `Skill {"skill": <name>}`, and reports CLI failures as errors. On the same set: **4/4, FP 0, FN 0, errors 0** (live, ~3 s per query). `run_loop_pro.py` runs upstream's `run_loop` with the fixed eval: imports and `--help` are VERIFIED. A full optimization run is NOT RUN because there's no `anthropic` package or API key here. Audit: medium (the `claude -p` subprocess call plus a docstring that mentions `pip install`).

## Tests

`python -m pytest -q tests` → **105 passed** (9 in `tests/test_skill_anything_pro.py`; mutation: dropping `--verbose` → 1 failure). Earlier: **96 passed** (56 in `tests/test_skills_manager.py`, 40 existing). These are unit and integration tests: sources are real local git repos and HOME is a temp folder. **They don't exercise the live `claude` CLI**; the live checks above do, and CI can't run them (no logged-in CLI there).
GitHub CI on commit `8679b92` (run #97: `check`, `service` ×2, `termux`, `apex`): **PASS**.
Mutation checks: disabling the high-risk block → 2 failures. Disabling the `remove --yes` guard → 1 failure.

## Security and compatibility report

`audit` over every local skill: high 0 · medium 7 · low 6 · none 16 (the details are in `reports/skills-audit.json`). The medium ones are claude.ai-synced document skills that run scripts and call subprocesses (`docx`, `pptx`, `xlsx`, `google-workspace`, `stratawright-daw`), plus `import-memory` and `skill-creator`. Those two are defensive mentions, downgraded from high, never lower.

Scan of the 76 remote skills (2026-10-23): high 0 · medium 18 · low 11 · none 47. Before the context rule, 6 official or catalogued skills scored high on **defensive** text ("never run `curl | sh`", "can't exfiltrate a vaulted credential", "Do not tell the user they need…"). Each line was read by hand; all six were false positives. Fixes: in docs and code comments, a high match next to a warning word becomes medium, so a human still reviews it. The concealment rule now matches only hiding phrasing. An env-plus-network script is medium only when every host it names is a first-party API (for example `api.anthropic.com`).

Compatibility: every install is recorded as `compatible: ["claude-code"]`. Codex reads `.agents/skills/`. The tool lists that folder but doesn't install into it.

## Known limits and next steps

- The scan is a line-based heuristic. It can't follow obfuscation across lines or files, or see what an allowed network call sends. Treat medium as "read it", not "fine".
- Search is lexical (idf plus a small synonym map). Unrelated installed skills can still appear as a second pick when they share words ("page", "web"). The agent must read the description before using one.
- Backups (`backups/`) are gitignored and live in the container, so they vanish with it. The committed registry still records source and commit, so an install can be repeated.
- Pins are commit SHAs, not signatures: they stop silent upstream changes, but they don't prove who wrote a commit. Moving a pin still needs a human review of the diff (`update` lists the changed files).
- Next: a Codex adapter once a Codex CLI is available to verify it.
