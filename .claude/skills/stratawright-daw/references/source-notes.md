# Upstream docs vs code

Checked at `Goldwaterfung/Stratawright` commit `35008ae` (2026-10-11). Paths
are under `src/Agentic layer/`. After a Stratawright upgrade, re-check these
lines; if a gap has been fixed upstream, update `SKILL.md` and `commands.md`.

| # | Upstream doc / FAQ says | Code does | Where |
|---|---|---|---|
| 1 | `daw-cli` exits with the error code | exits 0 whenever it connected, even on `ERROR 7x` | `client/main_client.cpp:111` |
| 2 | (silent) | reply read once into a 4096-byte buffer, so long output is cut off | `client/main_client.cpp:105` |
| 3 | `prep gain-stage` reaches a target RMS (FAQ: "inspects peak and RMS") | sets each fader to `10^(target/20)`, with no measurement | `server/handlers/track_handler.cpp:450` |
| 4 | `midi add-note` flags: track, clip, pitch, velocity, start, dur | `--channel` is also required | `server/handlers/clip_handler.cpp:230` |
| 5 | `track create` has defaults for name/type/color | all three required | `server/handlers/track_handler.cpp:162` |
| 6 | `route send` defaults `--db -12 --tap post` | `--db` and `--tap` required | `server/handlers/routing_handler.cpp:91` |
| 7 | `route sidechain` defaults `--slot 0 --db 0` | both required | `server/handlers/routing_handler.cpp:171` |
| 8 | `clip move --to-track` optional | required | `server/handlers/clip_handler.cpp:557` |
| 9 | error 74 symbol `RESOURCE_BUSY_USER_TOUCH` | prints `RESOURCE_BUSY` | `common/ipc_protocol.h:40` |
| 10 | error 73 blocks edits during playback | no handler returns 73 | grep `ENGINE_PLAYING_LOCKED` in `server/handlers/` |
| 11 | error 75 on `set-param` outside 0–1 | not checked in `plugin_handler.cpp`; 75 only from export enqueue failures | `server/handlers/rendering_handler.cpp:135,250` |
| 12 | `--format json` for programmatic output on every command | `export` reads `--format` as the codec, so its replies use the default format | `server/handlers/rendering_handler.cpp:79,162` |
| 13 | (silent) | an empty list prints `OK <SYMBOL>`, not `[]` | `server/result_formatter.cpp:15` |
| 14 | (silent) | `DAW_CLI_DEFAULT_FORMAT` is read by the **server** process | `common/parsed_args.cpp:125` |
| 15 | FAQ: "atomic multi-command batching" | one command per connection, no transaction | `server/ipc_server.cpp` accept loop |
| 16 | FAQ: AI "creates, configures, and **arms** tracks" | no record-arm or input command exists | no handler |
| 17 | Skill's reference links | absolute `file:///Users/...` paths that only work on the author's Mac | upstream `skills/daw-cli/SKILL.md` |

Things this skill does **not** claim, because they weren't verified here:
real-time safety numbers (< 5 ms per command, "zero dropouts"), Windows IPC
(the socket code is POSIX), and how the analysis engine taps the signal
(pre- or post-fader). The wrapper's `gain-stage` re-measures after
applying so that last point is caught at run time instead of assumed.

## How this was verified (2026-10-23)

| Check | Result |
|---|---|
| Real IPC server (`ipc_server`, `command_dispatcher`, `result_formatter`, `parsed_args`, all handlers except `analysis`) + real `daw-cli`, built from `35008ae` with g++ 13 on Linux, no DAW controllers wired | VERIFIED: stock client prints `ERROR 70 ...` and exits 0; wrapper exits 70; wrapper's wire format is accepted and its JSON parsed; `--value -0.25` parses as a value; `track create` without `--color` fails as documented here |
| `analysis_handler` | NOT BUILT: needs Eigen. Output fields taken from the source |
| Handlers that check a controller before arguments (route, midi, export) | Argument rules taken from the source; the harness can't reach them without controllers |
| Wrapper logic (errors, empty lists, >4 KB replies, TSV export replies, dry-run, journal, batch stop, gain-stage maths and verification) | VERIFIED: `tests/test_stratawright_skill.py`, fake server using the real formatter's output shapes |
| Against a running Stratawright app with audio and plugins | NOT VERIFIED: needs the user's Mac or PC |
