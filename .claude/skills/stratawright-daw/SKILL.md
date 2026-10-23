---
name: stratawright-daw
description: >-
  Drive the Stratawright DAW (open-source C++20 agentic DAW) through its daw-cli
  IPC socket like a professional engineer: session setup, track creation and
  colouring, real measurement-based gain staging, bus and send routing,
  sidechains, VST3/AU/CLAP plugin chains, clip and MIDI editing, masking,
  resonance, phase and loudness analysis, and master or stem export with
  delivery loudness checks. Use whenever the user mentions Stratawright,
  daw-cli, /tmp/daw_session.sock, or asks an agent to record, prep, mix,
  gain-stage, route, analyze or export a session in Stratawright.
---

# Stratawright DAW: pro control

You are the session engineer. The DAW is controlled through a UNIX socket
(`/tmp/daw_session.sock`) served by the running Stratawright app. Every command
is one request; there is no undo through the CLI, so you act like an engineer
on a paid session: inspect, plan, change, verify.

Everything in this skill was checked against the Stratawright source
(`Goldwaterfung/Stratawright` @ `35008ae`, Oct 2026). Where the project's own
docs or FAQ disagree with the code, this skill follows the code. See
[`references/source-notes.md`](references/source-notes.md).

## Use the wrapper, not bare daw-cli

```bash
W=".claude/skills/stratawright-daw/scripts/daw.py"   # or ~/.claude/skills/stratawright-daw/scripts/daw.py
python3 "$W" run status
python3 "$W" run track list
python3 "$W" --dry-run run track delete --track 4      # shows what would be sent
python3 "$W" batch plan.txt                            # stops at the first failed line
python3 "$W" snapshot                                  # status + tracks + routing
python3 "$W" gain-stage --track 1..8                   # measure and plan; --apply to change
```

Why: the stock `daw-cli` **exits 0 even when the DAW answers `ERROR 72 ...`**
and **cuts every reply at 4,095 bytes**. The wrapper reads the whole reply,
returns one JSON object (`ok`, `code`, `symbol`, `message`, `fields` or
`rows`), exits with the real protocol code (70–76), asks for JSON output
for you, and appends every mutation to `~/.cache/stratawright/journal.jsonl`.
If you must use bare `daw-cli`, treat any stdout line starting with `ERROR `
as a failure whatever the exit code says, and keep lists short with
`--filter` / `--head`.

## The engineer's loop (always)

1. **Connect.** `run status`. Code 71 means the app isn't running: ask the
   user to open Stratawright. Don't retry in a loop.
2. **Inspect before you touch.** `snapshot`, plus `clip list --track N` and
   `plugin list --filter ...` as needed. Take every track ID, clip ID and
   plugin name **from output**, never from memory or the user's numbering.
   Track IDs are not positions; they can have gaps after deletes.
3. **Plan out loud.** For anything over three changes, write the commands
   into a batch file, show the user a short plan, and run it with
   `--dry-run` first when something is destructive (`delete`, `--overwrite`,
   `merge`, `trim-silence`, `split`).
4. **Stop the transport** before structural edits (create, delete, route,
   plugin add/copy). The `ENGINE_PLAYING_LOCKED` (73) code exists, but no
   handler checks for it at this commit, so the engine won't protect you.
5. **Change in small steps**, then **verify** by reading state back
   (`track inspect`, `route list`, `clip list`) or re-measuring (`analyze`).
   A command that printed OK hasn't been verified.
6. **Report like an engineer:** what changed (IDs, values), what you measured
   before and after, what you could not do and why.

## Hard rules

- **Confirm before destroying.** `track delete`, `--overwrite`, `clip merge`,
  `trim-silence` and overwriting an export path all need the user's go-ahead.
  The CLI has no undo.
- **Never invent a command or flag.** If it isn't in
  [`references/commands.md`](references/commands.md), it doesn't exist. Common
  hallucinations: record-arm, track rename, plugin remove/bypass, plugin
  parameter names, automation, session save/load, undo. Say plainly that the
  CLI can't do it and suggest the GUI.
- **Plugin parameters are blind.** `plugin set-param` takes a parameter
  *index* and a normalized `0.0–1.0` value, and the CLI cannot read parameter
  names or current values. Only set an index the user or the plugin's own
  docs identified. Never sweep indices to find out what they do on a live
  session.
- **`prep gain-stage` is not gain staging.** At this commit it sets every
  listed fader to the target number (for example -18 dB) without measuring
  anything. Use the wrapper's `gain-stage`, which measures with
  `analyze loudness`, then moves clip gain (pre-insert, so plugins see the
  right level) and re-measures.
- **Plugin names are exact and case-sensitive.** Run
  `plugin list --filter "<part>"` and copy `NAME` byte for byte, or use
  `--id`.
- **`midi add-note` needs `--channel`.** It's required by the code and
  missing from the upstream docs.
- **`track create` needs all of `--name`, `--type`, `--color`.** No defaults.
- **No `"` characters in names or paths.** The server's tokenizer can't carry
  them, and they break its JSON output.
- **`export --format` is the audio codec** (`wav|flac|mp3|aiff|ogg`), so
  export replies come back as TSV. The wrapper parses that.
- **Honest numbers only.** Quote measured values from `analyze`. Never
  report LUFS, peaks or "it sounds better" you didn't measure or hear. The
  analysis tells you levels and conflicts, not taste: say so when a
  decision is subjective.

## Levels you work to

| Stage | Target | Why |
|---|---|---|
| Tracking / gain staging | about -18 dBFS RMS per source, peaks ≤ -6 dBFS | -18 dBFS ≈ 0 VU on most analog-modelled plugins; leaves headroom on buses |
| Mix bus before mastering | peaks -6 to -3 dBFS, no limiter needed | headroom for the master |
| True peak on any lossy delivery | ≤ -1.0 dBTP | inter-sample overs after encoding |
| Streaming master (Spotify, YouTube, Amazon) | about -14 LUFS integrated | platforms turn louder masters down |
| Apple Music | about -16 LUFS integrated | Sound Check reference |
| Podcast / voice | -16 LUFS (stereo), -19 LUFS (mono) | common spoken-word spec |
| Broadcast EBU R128 | -23 LUFS ±0.5 LU, ≤ -1 dBTP | EBU R128 |
| US broadcast ATSC A/85 | -24 LKFS, ≤ -2 dBTP | ATSC A/85 |

Platform targets drift. Treat them as normalization references, not laws,
and follow a spec the user gives you over this table.

## Where to look

- [`references/commands.md`](references/commands.md): every verb, subcommand
  and flag the server really accepts, with required/optional and output
  fields.
- [`references/workflows.md`](references/workflows.md): pro recipes. Session
  setup from a template, real gain staging, drum bus with parallel
  compression, vocal chain and FX sends, kick/bass sidechain, masking and
  resonance fixes, multi-mic phase, short-form video (voice over music),
  mix/master delivery with loudness checks, and stems.
- [`references/errors.md`](references/errors.md): codes 70–76, what really
  triggers each, and the recovery.
- [`references/source-notes.md`](references/source-notes.md): where upstream
  docs and code disagree, with file references, so you can re-check after an
  upgrade.
