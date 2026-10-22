# Update Logs (complete history, newest first)

{=====================Update Log=====================}
{2026-10-22 21:30 · 2}
{Request: guard HarnessFlow's generated files against drift}
- .github/workflows/test.yml: check job regenerates agent definitions and entry points and fails on any change.
- AGENT.md HarnessFlow row: how to regenerate after editing agents/*.agent.md.
- Resolved known issue: generated HarnessFlow files can drift.

{=====================Update Log=====================}
{2026-10-22 21:27 · 1}
{Request: fix the bot's localhost default and the admin check, and keep both fixes from regressing}
- bot.py: OmniRoute default http://127.0.0.1:20128/v1; new is_admin()/allowed() gate fails closed and tells an unset owner their ID.
- .env.example, README.md: 127.0.0.1; TELEGRAM_ADMIN_ID documented as required.
- tests/test_bot.py (new, 10 tests) + CI check job runs them; 4 of them fail on the old code.
- AGENT.md: Bot access rule, Common Tasks, file table, trap 11.
- Resolved known issues: localhost default, fail-open admin gate, no bot tests.
