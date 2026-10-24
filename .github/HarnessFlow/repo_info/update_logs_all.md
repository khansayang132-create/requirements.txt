# Update Logs (complete history, newest first)

{=====================Update Log=====================}
{2026-10-23 20:57 · 5}
{Request: scheduled repo-improver run #3}
- apex/apex/tts.py EspeakProvider: pass '--' before the narration. espeak-ng read text starting with '-' (e.g. '-50% itu bukan diskon') as an option, exited 0 and wrote no WAV, so the job failed with 'no usable audio' and retried until dead-lettered.
- apex/tests/test_media.py: test_espeak_speaks_narration_that_starts_with_a_dash; it fails before the fix and passes after (run in an ubuntu:24.04 container with real espeak-ng and ffmpeg).
- Test count 87 -> 88 in AGENT.md, apex/README.md, apex/STATUS.md and the overviews. The termux cleanup race this run first looked at was already fixed on main (0bf42b3).

{=====================Update Log=====================}
{2026-10-23 16:52 · 4}
{Request: scheduled repo-improver run #2; the owner's phone log showed telegram.error.TimedOut crashes}
- bot.py: new build_app() with 30 s Telegram timeouts (library default 5 s); main() runs run_polling(bootstrap_retries=-1) so startup retries instead of exiting.
- Reproduced against a local server that never answers: old code exits after 5.1 s on its first attempt; fixed code was still retrying (3 attempts) when stopped at 70 s.
- tests/test_bot.py: 2 tests (both fail on the old code). AGENT.md trap 12.

{=====================Update Log=====================}
{2026-10-23 14:50 · 3}
{Request: scheduled repo-improver run #1 (owner asked for continuous improvement)}
- apex/apex/tts.py normalize_for_speech: decimal comma read as 'koma' + digits, and a scale word after an Rp amount moves before 'rupiah' ('Rp1,5 juta' -> 'satu koma lima juta rupiah'; was 'satu rupiah,lima juta').
- apex/tests/test_core.py: 6 parametrized cases (5 failed before the fix).
- Test count 81 -> 87 in AGENT.md, apex/README.md, apex/STATUS.md and the overviews. Sample narration reads the same, so the committed sample output is unchanged.

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
