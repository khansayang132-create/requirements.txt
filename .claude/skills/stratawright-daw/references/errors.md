# Error codes and recovery

Format on the wire: `ERROR <code> <SYMBOL> "<message>"`. The stock `daw-cli`
exits with the code **only** for 71 (and 70 when called with no arguments);
everything the server reports arrives with exit 0. `scripts/daw.py` exits
with the real code.

| Code | Symbol | What actually triggers it (at 35008ae) | Recovery |
|---|---|---|---|
| 70 | `INVALID_ARGS` | missing required flag, bad number, unknown verb/subcommand, bad range, exceptions inside handlers | Re-read the row in `commands.md`. The message names the missing flags. Fix and resend once |
| 71 | `DAW_NOT_RUNNING` | socket missing or refused; also a controller not wired in the app | Ask the user to start Stratawright. Don't loop |
| 72 | `ENTITY_NOT_FOUND` | track, clip or plugin ID missing; plugin name not an exact match | `track list` / `clip list --track N` / `plugin list --filter`, then use the exact value |
| 73 | `ENGINE_PLAYING_LOCKED` | defined but **not emitted by any handler** at this commit | Stop the transport before structural edits anyway |
| 74 | `RESOURCE_BUSY` (docs say `RESOURCE_BUSY_USER_TOUCH`) | `plugin copy`/`copy-chain` into an occupied slot without `--overwrite` | Ask before adding `--overwrite`: it replaces the existing plugin |
| 75 | `PLUGIN_FAULT` | export/stem job failed to enqueue | Check the output path is writable and absolute, then `job list`. Note: `set-param` does **not** range-check `--val`, so clamp it yourself |
| 76 | `ASSET_I_O_ERROR` | `clip add-audio` path unreadable or bad format | Check the file exists (absolute path), is readable, and is WAV/AIFF/FLAC |
| 1 | `TIMEOUT` (wrapper) | no reply within `--timeout` | The command may have run. Inspect state before retrying a mutation |

Retry policy: never blindly resend a **mutation** after a timeout or an
unclear reply, because it can apply twice (two tracks, double gain). Read
state, then decide.
