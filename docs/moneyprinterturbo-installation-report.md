# MoneyPrinterTurbo Video Skill — Installation Report

| Field | Value |
|---|---|
| A. Source repository | https://github.com/ermradulsharma/money-printer-turbo (branch `main`, path `docs/skill/`) |
| B. Commit SHA | `cc14369aa489ed2567b37ccdd24b29e2a1ffc9f8` (committed 2026-10-29T14:41:10+05:30) |
| C. Installed at | 2026-11-08T20:10Z (UTC) |
| D. Destination | `/root/.claude/skills/moneyprinterturbo-video/` (`CLAUDE_CONFIG_DIR` unset → default `~/.claude`) |
| Environment | Linux x86_64 (kernel 6.18.44), bash, Claude Code 2.1.319, Python 3.13.18, uv present — ephemeral cloud container |

## E–G. Files

| File | Size | Mode | SHA256 |
|---|---|---|---|
| SKILL.md | 7054 B | 644 | `78ab5194e943a0e346bc2f8a1a8efa741a73fd56342d86a7ffd1bb897f517a81` |
| mpt_agent.py | 24000 B | 755 | `4231f4f38f9cf87f4ff4e57f42d92c8b17950da65f9a0ebf34e29b987f03bf91` |

Both files were verified byte-identical to the upstream clone with `cmp`. They were installed atomically (staged in a temp dir, then `mv -T`). No earlier install existed, so no backup was needed.

## Security audit (both files read in full)
- subprocess: list arguments only, no `shell=True`. Commands are `uv sync --frozen` and `uv run python cli.py …`. Nothing runs at install time.
- Network: downloads the project ZIP from GitHub and sends the Pexels key to `api.pexels.com` to validate it. Nothing else is sent anywhere.
- Env vars read: only `MPT_LLM_*` and `MPT_PEXELS_API_KEY`.
- Deletion: only `rmdir` of an empty install dir. ZIP extraction checks every path so nothing lands outside the target folder.
- Credentials are written to `~/MoneyPrinterTurbo/config.toml` and never printed.
- Verdict: **suitable for installation.** No malicious behaviour found.

## H–J. Validation
- H. Frontmatter: valid YAML. `name` = `moneyprinterturbo-video` (matches the directory). The description names MoneyPrinterTurbo video generation. Keys: name, description, compatibility, metadata. **PASS**
- I. Helper: adjacent to SKILL.md and referenced by relative name. `py_compile` syntax check passes; the helper was not executed. **PASS**
- J. Discovery: a fresh `claude -p` process listed `moneyprinterturbo-video`, and the running session hot-loaded it with its full description. **PASS**

## K. Compatibility
- The skill declares support for macOS and Windows only. This host is **Linux**, which is **not supported**. The skill is installed and discoverable, but running it here is untested and outside upstream's declared scope.
- Termux/Android is also not supported.

## L. Warnings
1. Fork, not the original: the repo is `ermradulsharma/money-printer-turbo`, but the metadata author is harry0703 (the author of the original `harry0703/MoneyPrinterTurbo`).
2. Unpinned code: on first run the helper downloads `main.zip` (always the latest, not this audited commit), then runs `uv sync` and `cli.py`. That code was **not** audited.
3. The Moonshot/Kimi and VolcEngine signup links carry affiliate/tracking parameters.
4. The default language is **Chinese** (voice `zh-CN-XiaoxiaoNeural`). For Indonesian, pass `-- --voice-name id-ID-GadisNeural-Female` (verify with `cli.py --help`).
5. Ephemeral host: `/root/.claude` is wiped when this cloud container is reclaimed. A durable copy is committed to the repo at `.claude/skills/moneyprinterturbo-video/`.

## Definition of Done
| Item | Status |
|---|---|
| Official repository inspected | PASS |
| Source files audited | PASS |
| Personal skills directory identified | PASS |
| Existing skill backed up | PASS (none existed — N/A) |
| SKILL.md installed | PASS |
| mpt_agent.py installed | PASS |
| Directory structure verified | PASS |
| YAML frontmatter validated | PASS |
| SHA256 checksums recorded | PASS |
| Claude Code discovers the skill | PASS |
| Compatibility checked | PASS (result: Linux unsupported) |
| Installation report created | PASS |
| Runtime video generation | NOT TESTED (out of scope by request) |
