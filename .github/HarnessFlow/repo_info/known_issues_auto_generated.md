# Known Issues (auto-generated)

Found by HarnessFlow initialize (fast) on 2026-10-22, from a read of the key scripts. The capability gaps tracked in `apex/STATUS.md` (BLOCKED / NOT IMPLEMENTED) are not repeated here; that file owns them.

## OmniRoute default URL uses `localhost`, against the repo's own trap #1
`OMNIROUTE_BASE_URL` defaults to `http://localhost:20128/v1` in `bot.py:17` and `.env.example:6`, and `README.md:26` tells users to leave it that way.
Root cause: the defaults were written before the phone setup showed that `localhost` fails there. AGENT.md trap #1 says to use `127.0.0.1`, and the termux runner and Headroom docs already do.
Consequences: a fresh install on the phone that keeps the default `.env` can't reach OmniRoute, and `/ping` reports it unreachable. The owner's working `.env` presumably overrides it (not verified).

## Bot is open to everyone when `TELEGRAM_ADMIN_ID` is unset
`generate()` (`bot.py:81`) and `ping()` (`bot.py:134`) check `if ADMIN_ID and user_id != ADMIN_ID`, so an empty `TELEGRAM_ADMIN_ID` turns the check off.
Root cause: the gate fails open instead of closed.
Consequences: anyone who finds the bot's username can run `/hook`, `/script`, `/caption` and `/idea`, which spends the owner's AI quota on OmniRoute or OpenAI. AGENT.md's rule ("every command that spends AI calls checks `TELEGRAM_ADMIN_ID` first") is met in form but not in effect.

## Bot's only CI check is `py_compile`
The `check` job compiles `bot.py` but never imports or runs it, and there are no bot tests.
Root cause: the bot predates APEX's test suite, and its behaviour depends on Telegram and an AI gateway.
Consequences: route ordering, Headroom fallback, message splitting and the admin gate can regress without CI noticing. The same pattern is already tested for APEX with local stub servers (`test_ideas.py`, Headroom-first routing).

## Generated HarnessFlow files can drift from the vendored pack
`AGENTS.md`, `.github/copilot-instructions.md`, `.claude/agents/`, `.claude/rules/` and `.codex/agents/` are copies made by `.github/HarnessFlow/cli_setup.sh`.
Root cause: they are generated, not hand-maintained, and CI doesn't check them.
Consequences: editing `.github/HarnessFlow/agents/*.agent.md` without running `python3 sync_agent_definitions.py` and `bash .github/HarnessFlow/cli_setup.sh` leaves stale agent definitions. The new agent types are only picked up by sessions started after they are on the branch.
