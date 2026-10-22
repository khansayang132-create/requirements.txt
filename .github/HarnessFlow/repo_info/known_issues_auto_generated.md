# Known Issues (auto-generated)

Found by HarnessFlow initialize (fast) on 2026-10-22, from a read of the key scripts. The capability gaps tracked in `apex/STATUS.md` (BLOCKED / NOT IMPLEMENTED) are not repeated here; that file owns them.

## Generated HarnessFlow files can drift from the vendored pack
`AGENTS.md`, `.github/copilot-instructions.md`, `.claude/agents/`, `.claude/rules/` and `.codex/agents/` are copies made by `.github/HarnessFlow/cli_setup.sh`.
Root cause: they are generated, not hand-maintained, and CI doesn't check them.
Consequences: editing `.github/HarnessFlow/agents/*.agent.md` without running `python3 sync_agent_definitions.py` and `bash .github/HarnessFlow/cli_setup.sh` leaves stale agent definitions. The new agent types are only picked up by sessions started after they are on the branch.
