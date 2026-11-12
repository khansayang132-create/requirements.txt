# Wonderland Studio — status

VERIFIED = run and checked here, with the evidence named. IMPLEMENTED = written and unit-tested, but the
real external service was not available, so it has not run for real. BLOCKED = needs the owner.

Last updated 2026-11-12.

## Verified

| What | Evidence |
|---|---|
| Whole production line, story → finished MP4 | `run-cycle` in a fresh state folder: 9 episodes planned, 8 produced and passed every gate, 1 rejected by quality control (frozen picture) three times and left empty instead of published. |
| Real 3D toon characters (Three.js, Chromium/SwiftShader) | 617-frame episode in 117.6 s, QA pass; 22 tests (`tests/test_render3d.py`); character sheet and 7-angle turnarounds looked at by eye. |
| 2D fallback renderer | Same seed: 617 frames in 33 s, QA pass. Used automatically when Chromium is missing (phone). |
| Layered Foley, ambience, stings, ducking, 48 kHz master | 4 episodes: −13.8 to −14.0 LUFS, true peak ≤ −2.1 dBTP, voice 17–18 dB above the bed; 23 tests (`tests/test_audio.py`). |
| Story variety | 71 formats; 365-day simulation: 1460/1460 slots filled, 0 repeats, similarity ≤ 0.62 (`tools/simulate_runway.py`); 281 tests. Spell check over every generated word. |
| Queue, retries, recovery, gates, publishing logic | 23 tests (`tests/test_company.py`) with YouTube faked: crash recovery, backoff, blocked work, QC regeneration, review approval bound to the file hash, first upload as a test, no re-upload after a crash, "published" only when YouTube says public. |
| Dashboard | Rendered from a real state database; design-check 0 errors, 0 warnings at 390/1440 px, light and dark. |
| Your `3d-cartoon-studio` skill | Installed at `.claude/skills/3d-cartoon-studio/`, skills-manager audit low risk, discovered by Claude Code. |

Full suite: 349 passed.

## Implemented, not yet run for real

| What | Why not verified | How it gets verified |
|---|---|---|
| Free neural voice (Kokoro) | Model download hosts are blocked in this sandbox; episodes here use the robotic eSpeak fallback. | CI job `wonderland` installs Kokoro and checks it speaks. |
| Upload, schedule, playlists, verify on YouTube | No channel and no Google sign-in exist yet. | Owner steps 1–4 in the README, then one review-mode test upload. |
| Analytics, reports with numbers, experiments | Need published videos. | Automatic once videos are public. |
| Telegram notifications | No bot token; Telegram is blocked here. Notifications are stored in the database and shown in `status`/dashboard. | Set `WONDERLAND_TELEGRAM_TOKEN` and `WONDERLAND_TELEGRAM_CHAT`. |

## Blocked on the owner

1. Create the channel in YouTube Studio (the API cannot) and set it to *made for kids*. `python -m wonderland channel-kit` has the texts. Check the name with a trademark search.
2. Google Cloud project + Desktop OAuth client, then `authenticate.py --scopes upload,manage,analytics`.
3. `YOUTUBE_DRY_RUN=false`, then `publishing.mode: review`.
4. Somewhere to run every day: the phone (`python -m wonderland daemon` in Termux, 2D look) or a computer/server with Chromium (3D look).

## Known weak spots

- 3D: Toto's trunk hides most of his neckerchief; in 3/4 view the far eye pokes slightly past the head outline; a raised wave is a little lower than in 2D; actors share one depth plane.
- The grade pass made the 2D renderer ~2.7× slower and cannot be switched off from config yet.
- The year-long runway leans on a few formats (e.g. `starts_with` 118 times, `which_one` 62): different scripts, but similar shape. YouTube's 2025 "inauthentic content" rule targets repetitive, templated videos, so review mode, the owner's eye and more formats (or an LLM story writer, `LLMStoryProvider`) matter for year two.
- Audio constants (bus gains, ducking amounts, sample rate) live in code, not yet in `studio.yaml`.
- No scheduled GitHub workflow runs the studio; it runs wherever the owner starts `daemon` or `run-cycle`.
