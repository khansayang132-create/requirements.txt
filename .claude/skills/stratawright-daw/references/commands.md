# daw-cli command reference (verified)

Checked against `src/Agentic layer/server/handlers/*.cpp` at Stratawright
`35008ae`. **Req** = the handler rejects the command without it. Defaults are
the code's defaults, not the docs'. Send these through
`scripts/daw.py run <command>`.

## Contents
- [Grammar](#grammar) · [Output](#output) · [status / transport](#status--transport)
- [track](#track) · [prep](#prep) · [plugin](#plugin) · [route](#route)
- [clip / midi](#clip--midi) · [analyze](#analyze) · [export / job](#export--job)
- [What the CLI cannot do](#what-the-cli-cannot-do)

## Grammar

- `daw-cli <verb> [<subcommand>] [--flag value | --switch] ...`
- The first token after the verb is the subcommand unless it starts with `-`.
- A flag followed by another flag (or nothing) becomes the switch value
  `true`. `--on false` / `--on 0` count as off.
- Negative numbers are fine as values (`--db -3.5`, `--by -1/16`). Only `-`
  followed by a letter is read as a flag.
- **Track ranges** (`--track`, `--from`, `--to-tracks`): `3`, `1..4`,
  `1..4,7,9..10`. Single-track commands take the first ID of a range.
- **Positions** are bars.beats.ticks: `1.1.0` is the downbeat of bar 1.
  `--dur 4.0.0` is four bars.
- One command per connection. The server handles connections one at a time.
  There is no transaction or atomic batch.
- Max command length is 4,095 bytes. No `"` or newlines inside values.

## Output

`--format json|tsv|kv|pretty`. The server's default is TSV, or
`$DAW_CLI_DEFAULT_FORMAT` **in the DAW's own environment** (the server
formats replies, so setting it for the client does nothing).

- Error: `ERROR <code> <SYMBOL> "<message>"`. The stock client still exits
  0 when this comes back.
- Success with no fields, or an **empty list**: `OK <SYMBOL>`, even with
  `--format json`.
- JSON: every value is a string (`"GAIN_DB":"-3.5"`), keys sorted A–Z, no
  escaping. The wrapper turns numbers and booleans into real types.
- In JSON/TSV/KV, single-result successes don't include the symbol. Only
  `pretty` prints it.

## status / transport

| Command | Req | Notes |
|---|---|---|
| `status` | | transport state, tempo, time signature, position |
| `transport play` / `transport stop` | | |
| `transport set-tempo --bpm 128` | `--bpm` (alias `--tempo`) | |
| `transport set-time-signature --num 6 --den 8` | `--num`, `--den` | both required |

## track

| Command | Req | Notes |
|---|---|---|
| `track list` | | rows: `ID NAME TYPE GAIN_DB PAN MUTE SOLO` |
| `track inspect --track 3` | `--track` | same fields for one track |
| `track create --name "Vox Lead" --type audio --color yellow` | all three | type `audio`, `midi`/`instrument`, `aux`/`bus`, `folder`. Returns `id`, `name`, `type` |
| `track create-batch --names "Kick,Snare,OH L,OH R" --type audio` | `--names`, `--type` | rows `ID NAME TYPE`. No colour flag: follow with `auto-color` or `set-color` |
| `track set-gain --track 1..4 --db -3.5` | both | fader, dB |
| `track set-pan --track 2 --value -0.3` | both | -1.0 left … +1.0 right |
| `track set-mute --track 2 --on` / `set-solo` | `--track` | omit `--on` (or `--on false`) to clear |
| `track set-color --track 1..4 --color red` | both | `red blue green yellow purple orange cyan pink white grey/gray black` or `#RRGGBB` |
| `track auto-color` | | colours by instrument keywords in names |
| `track sanitize-names` | | trims, strips `.wav`/`.mp3`, `_` → space. Changes every track: confirm first |
| `track delete --track 4` | `--track` | **destructive, no undo** |

## prep

| Command | Req | Notes |
|---|---|---|
| `prep gain-stage --track 1..8 --target-rms -18` | both | **Sets each fader to `--target-rms` dB. It doesn't measure.** Use `daw.py gain-stage` instead |

## plugin

| Command | Req | Notes |
|---|---|---|
| `plugin scan` | | returns `scanned_count` |
| `plugin list --filter "pro-q" --category effect --head 20` | | rows `ID NAME VENDOR CATEGORY FORMAT`. Filter is case-insensitive on name/vendor. Category `effect`/`fx`, `instrument`/`synth`. Always filter: the stock client truncates long lists |
| `plugin add --track 1 --name "Pro-Q 3" --slot 0` | `--track`, `--name` or `--id` | exact, case-sensitive name. Slots `0..7` |
| `plugin set-param --track 1 --plugin 0 --param 3 --val 0.75` | `--track`, `--plugin`/`--slot`, `--param`, `--val` | index + normalized value. **The server doesn't range-check `--val`: clamp it to 0.0–1.0 yourself** |
| `plugin copy --from-track 1 --slot 0 --to-tracks 2..5 [--overwrite]` | `--from-track`, `--slot`, `--to-tracks` | 74 if a target slot is taken and no `--overwrite` |
| `plugin copy-chain --from-track 1 --to-tracks 2..5 [--overwrite]` | `--from-track`, `--to-tracks` | all 8 slots |

## route

| Command | Req | Notes |
|---|---|---|
| `route folder --track 1..4 --to 10` | both | sets main output and folder parent to bus/folder track `10` |
| `route send --from 2 --to 14 --db -12 --tap post` | **all four** | `--tap pre|post`. Docs claim defaults; code requires them |
| `route sidechain --source 1 --to-track 9 --slot 0 --db 0` | **all four** | feeds track 1 into the plugin in slot 0 of track 9 |
| `route list` | | rows `ID NAME TYPE MAIN_OUTPUT SENDS SIDECHAINS` |

## clip / midi

| Command | Req | Notes |
|---|---|---|
| `clip list --track 1 [--bar 1-8]` | `--track` | rows `CLIP_ID TRACK_ID NAME TYPE START_BAR START_FRAME DURATION_FRAMES GAIN_DB MUTED`. `--track 0` lists all tracks. Max 256 clips per call |
| `clip add-audio --track 1 --path "/abs/vocal.wav" --start 1.1.0` | all three | absolute path. 76 if unreadable |
| `clip add-midi --track 2 --start 1.1.0 --dur 4.0.0` | all three | |
| `midi add-note --track 2 --clip 1 --pitch C4 --velocity 100 --channel 1 --start 1.1.0 --dur 0.1.0` | **all seven, including `--channel`** | pitch `C4`, `Db5`, `F#3` or `0..127`. Channel isn't validated by the server: confirm the convention in the GUI on the first note |
| `clip set-gain --track 1 --clip 1 --db -3` | all three | pre-insert gain, which is what you use for gain staging |
| `clip set-mute --track 1 --clip 1 --on true` | all three | unlike `track set-mute`, `--on` must be present: unmute with `--on false` |
| `clip split --track 1 --clip 1 --at 2.1.0` | all three | |
| `clip move --track 1 --clip 1 --to-pos 3.1.0 --to-track 1` | **all four** | pass `--to-track` even when the track stays the same |
| `clip nudge --track 1 --clip 1 --by +1/16` | all three | |
| `clip quantize --track 2 --clip 1 --grid 1/16 --strength 0.8` | all four | strength 0–1. Around 0.6–0.8 keeps feel |
| `clip trim-silence --track 1 --clip 1 --threshold -48 --fade-ms 5` | all four | **destructive to the edit**: confirm |
| `clip merge --track 1 --start 1.1.0 --end 5.1.0` (or `--clips "1,2,3"`) | `--track` + range or list | **destructive**: confirm |

## analyze

All read-only. Run them on stopped transport over real audio. Numbers come
back as floats.

| Command | Req | Key fields |
|---|---|---|
| `analyze loudness --track 1` | `--track` | `INTEGRATED_LUFS SHORT_TERM_MAX_LUFS MOMENTARY_MAX_LUFS LRA_LU CREST_FACTOR_DB SAMPLE_PEAK_DBFS TRUE_PEAK_DBTP` |
| `analyze true-peak --track 1` | `--track` | `MAX_TRUE_PEAK_DBTP TOTAL_CLIPPING_EVENTS SAFETY_STATUS` |
| `analyze window --track 1 --start 9.1.0 --dur 8.0.0` | all three | momentary/short-term LUFS, peaks, `IS_CLIPPING`, crest, centroid, `STEREO_CORRELATION`, `SAFETY_STATUS`, `REC_GAIN_TRIM_DB` |
| `analyze spectrum --track 1` | `--track` | 7 bands: sub 20–60, bass 60–250, low-mid 250–500, mid 500–2k, high-mid 2–4k, highs 4–8k, air 8–20k Hz, plus centroid, tilt, rolloff |
| `analyze masking --track 1 --vs 2` | both | `OVERALL_MASKING_INDEX` 0–1, `COLLISION_RISK`, per-band range / amount / `RECOMMENDED_ACTION` |
| `analyze resonance --track 2` | `--track` | per peak: `FREQ_HZ NOTE PROMINENCE_DB Q_FACTOR SEVERITY REC_NOTCH_DB` |
| `analyze phase-matrix --track 1..4` | `--track` | `GLOBAL_GROUP_HEALTH`, worst pairs, `REC_ACTION_n` |
| `analyze phase-align --track 3 --vs 4` | `--track`, `--vs` (alias `--ref-track`) | `RECOMMENDED_SAMPLE_OFFSET`, `_TIME_OFFSET_MS`, correlation before/after. Window is ±128 samples |
| `analyze stereo-width --track 1` | `--track` | `MID_RMS_DBFS SIDE_RMS_DBFS MS_RATIO_DB STEREO_WIDTH_PCT MONO_FOLD_LOSS_DB` |

Estimated RMS is `SAMPLE_PEAK_DBFS - CREST_FACTOR_DB` (crest factor is
peak-to-RMS). No command returns RMS directly.

## export / job

`--format` here is the **codec**. Replies are TSV. Exports run as background
jobs: poll `job status`.

| Command | Req | Notes |
|---|---|---|
| `export master --output /abs/mix.wav` (alias `mixdown`) | — (`--output`/`-o`, default `/tmp/mixdown.wav`) | `--format wav|flac|mp3|aiff|ogg` (wav), `--bit-depth 16|24|32` (24), `--sample-rate` (project), `--dither on|off` (on), `--normalize on|off` (off), `--norm-db` (-0.1), `--range full|loop` (loop if looping), `--tail-ms` (1000), `--split-planar on|off` |
| `export stems --output /abs/stems/ --track 1..12` | — (default `/tmp/stems/`) | `--naming-pattern "{track_index:02d}_{track_name}"`, `--print-sends` (wet), `--bypass-sidechain`, `--disable-ghost-triggers`, plus codec/depth/rate/range/tail/normalize as above |
| `job list` | | `JOB_ID NAME TYPE STATUS PROGRESS OUTPUT` |
| `job status --id 3` | `--id` | `status`, `progress`, `status_message`, `destination` |
| `job cancel --id 3` | `--id` | |

Export defaults to the **loop** range when looping is on. Pass
`--range full` for a full-song bounce. Use dither only when reducing bit
depth (24 → 16). Don't normalize a master you've already limited.

## What the CLI cannot do

No record-arm or input selection, no track rename (only `sanitize-names`),
no plugin remove/bypass/reorder, no plugin parameter names or values, no
automation, no markers, no session open/save, no undo, no project sample-rate
change, no metering of the master bus as its own target unless it's a track
ID. Say so and point the user to the GUI; don't improvise around it with
other commands.
