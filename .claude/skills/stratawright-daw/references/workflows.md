# Pro workflows

Each recipe follows the same loop: **inspect → plan → change → verify →
report**. `W` is the wrapper path (`python3 .../scripts/daw.py`). IDs in the
examples are placeholders: take the real ones from `snapshot` /
`track list` output.

## Contents
1. [Session from a template](#1-session-from-a-template)
2. [Gain staging that measures](#2-gain-staging-that-measures)
3. [Drum bus + parallel compression](#3-drum-bus--parallel-compression)
4. [Vocal chain + reverb/delay sends](#4-vocal-chain--reverbdelay-sends)
5. [Kick → bass sidechain](#5-kick--bass-sidechain)
6. [Masking and resonance clean-up](#6-masking-and-resonance-clean-up)
7. [Multi-mic phase](#7-multi-mic-phase)
8. [Short-form video: voice over music](#8-short-form-video-voice-over-music)
9. [Mix check and master delivery](#9-mix-check-and-master-delivery)
10. [Stems and deliverables](#10-stems-and-deliverables)
11. [Session hygiene: "prep this for mixing"](#11-session-hygiene-prep-this-for-mixing)

---

## 1. Session from a template

Example ask: *"Pop template: 4 vocals, stereo acoustic, bass DI, drums on a bus."*

```text
# plan.txt (run: $W batch plan.txt)
transport stop
track create-batch --names "Kick,Snare,OH L,OH R" --type audio
track create --name "Drums Bus" --type bus --color red
track create-batch --names "Bass DI" --type audio
track create-batch --names "Ac Gtr L,Ac Gtr R" --type audio
track create-batch --names "Vox Lead,Vox Dbl,Vox Harm 1,Vox Harm 2" --type audio
track create --name "Vox Bus" --type bus --color yellow
track create --name "Verb" --type aux --color cyan
track create --name "Delay" --type aux --color cyan
track auto-color
```

Then **read IDs back** (`$W run track list`) and route with the real IDs:
`route folder --track <kick..OH R> --to <Drums Bus>`,
`route folder --track <vox ids> --to <Vox Bus>`. Finish with `snapshot` and
report a table of ID → name → output. Recording still needs the GUI: the CLI
can't arm tracks or pick inputs. Say so.

## 2. Gain staging that measures

`prep gain-stage` only sets faders to a number, so don't use it. Do this:

```bash
$W gain-stage --track 1..12                       # plan only: measured peak, est. RMS, offset per track
$W gain-stage --track 1..12 --apply               # clip gain (pre-insert), then re-measure
$W gain-stage --track 13..14 --via fader --apply  # tracks with no audio clips (e.g. instrument)
```

Defaults: target -18 dBFS RMS, peak ceiling -6 dBFS, refuses moves over
±24 dB (`--max-move`). Read the report:

- `limited_by: peak_ceiling` means it's a spiky source (snare, percussion).
  RMS ends up under target on purpose. That's correct; don't force it.
- `verified: false` means the re-measurement didn't move by the planned
  offset. The analysis may be reading post-fader, or the clip gain didn't
  apply. Stop and report. Don't stack another offset on top.
- `skip` with "silent" means no audio or an empty track.

Then pull **faders** for the balance. Gain staging sets level into the
plugins; the fader sets the mix.

## 3. Drum bus + parallel compression

1. `plugin list --filter "comp" --category effect --head 20` and pick
   with the user. Don't choose a paid plugin they don't own.
2. Glue on the bus: `plugin add --track <Drums Bus> --name "<exact>" --slot 0`.
3. Parallel: create an aux `Drums Crush`, send the drum tracks to it with
   `route send --from <kick..OH R> --to <Crush> --db -6 --tap post`, and add a
   heavy compressor there. Blend with the aux fader (start around -10 dB).
4. Check: `analyze phase-matrix --track <kick..OH R>` before and after.
   Parallel paths through plugins with latency should stay aligned (PDC).
   If `GLOBAL_GROUP_HEALTH` gets worse, report it.
5. `analyze loudness --track <Drums Bus>` for headroom: peaks should stay
   under -6 dBFS.

Plugin parameters: only set indices the user identified (for example "on
this compressor param 2 is threshold"). Otherwise tell them what to dial
in the GUI: "about 2–4 dB gain reduction on the bus, slow attack, auto or
fast release".

## 4. Vocal chain + reverb/delay sends

Typical order: **EQ (cleanup, high-pass) → compressor → de-esser → tone EQ
→ saturation**, with reverb and delay on **sends**, not inserts.

1. Build the chain on `Vox Lead`, slots 0–4, with exact names from
   `plugin list`.
2. Copy to the doubles: `plugin copy-chain --from-track <Lead> --to-tracks
   <Dbl..Harm 2>`. Add `--overwrite` only after confirming, because it
   replaces what's in those slots.
3. Sends: `route send --from <vox ids> --to <Verb> --db -18 --tap post` and
   `... --to <Delay> --db -22 --tap post`. Post-fader keeps the wet level
   following fader rides.
4. Harshness: `analyze resonance --track <Lead>` and report peaks with
   `SEVERITY: HIGH...` as frequency, note, Q and suggested notch dB, for the
   user to set on the EQ (the CLI can't read EQ band parameters).
5. Vocal sitting in the mix: `analyze masking --track <Lead> --vs <Ac Gtr L>`
   (repeat against keys/synths).

## 5. Kick → bass sidechain

1. Put a compressor that accepts sidechain on the bass, slot 0.
2. `route sidechain --source <Kick> --to-track <Bass> --slot 0 --db 0`.
3. `route list` and confirm `SIDECHAINS` on the bass row shows the kick.
4. `analyze masking --track <Kick> --vs <Bass>`. If the low bands show
   `SIDECHAIN_DUCK_PRIMARY_LOWS`, the sidechain is the right tool; the
   user sets the duck depth (start at 3–6 dB GR, fast attack, release
   timed to the tempo) in the GUI.
5. Stems: `export stems` keeps sidechains active unless you pass
   `--bypass-sidechain`. Muted triggers still duck unless you pass
   `--disable-ghost-triggers`. Ask which the user wants.

## 6. Masking and resonance clean-up

```bash
$W run analyze masking --track <vox> --vs <gtr>
$W run analyze resonance --track <gtr>
$W run analyze spectrum --track <gtr>
```

Turn the output into an **EQ plan**, not automatic moves:

| Finding | Typical move |
|---|---|
| `CUT_VS_TRACK_EQ_<f>HZ`, moderate | 2–4 dB bell cut on the *other* track at f, Q ≈ 1.5–3 |
| `SIDECHAIN_DUCK_PRIMARY_LOWS` | sidechain or dynamic EQ, not a static cut |
| resonance `HIGH_SEVERITY_SURGICAL_CUT` | narrow notch at the frequency, Q from output (≥ 8), depth `REC_NOTCH_DB` |
| `LOW_MID_BAND_DBFS` far above neighbours | 200–400 Hz mud: broad 2–3 dB cut |
| `AIR_BAND_DBFS` very low on vocal | gentle 10–12 kHz shelf, only after de-essing |

Cut on the less important source first. Re-run `masking` after the user
applies the EQ and report the `OVERALL_MASKING_INDEX` before and after.

## 7. Multi-mic phase

```bash
$W run analyze phase-matrix --track <snare top>..<snare bottom>
$W run analyze phase-align --track <snare top> --vs <snare bottom>
```

- `REC_ACTION FLIP_POLARITY_TRACK_n`: polarity flip is a GUI or plugin
  action. Tell the user; the CLI has no polarity command.
- `RECOMMENDED_SAMPLE_OFFSET` (±128 samples): convert to a nudge only if the
  grid allows it; otherwise report the ms value for the user to slip. Never
  nudge by a musical grid value to "fix" phase: 1/16 at 120 BPM is 125 ms,
  not a phase-sized move.
- Re-measure and report `CURRENT_CORRELATION` → `IMPROVED_CORRELATION`.

## 8. Short-form video: voice over music

Example ask: TikTok, Reels or Shorts audio. The voice must stay clear, and
the music supports it without taking over.

1. Tracks: `Voice` (audio), `Music` (audio), optional `SFX`. Gain-stage
   both (recipe 2).
2. Voice chain: high-pass around 80 Hz, compressor, de-esser. The voice
   should sit about 6–10 dB above the music by short-term loudness.
3. Ducking: compressor on `Music`, `route sidechain --source <Voice>
   --to-track <Music> --slot 0 --db 0`.
4. Check where the voice talks:
   `analyze window --track <Voice> --start <bar> --dur 4.0.0` and the same
   window on `Music`. Compare `SHORT_TERM_LUFS`. Then
   `analyze masking --track <Voice> --vs <Music>`. Cut the music around
   2–4 kHz if it masks speech.
5. Deliver: `export master --output /abs/short.wav --range full`, then
   measure (recipe 9). Aim for about -14 LUFS integrated and ≤ -1 dBTP:
   platforms normalize, and over-loud audio gets turned down and distorts on
   encode. Keep it short. Don't pad the tail (`--tail-ms 300` is plenty
   for speech).

## 9. Mix check and master delivery

Before bouncing:

```bash
$W run transport stop
$W run analyze loudness  --track <master or mix bus ID>
$W run analyze true-peak --track <master or mix bus ID>
$W run analyze stereo-width --track <master or mix bus ID>
```

| Check | Pass |
|---|---|
| Mix (pre-master) peaks | -6 to -3 dBFS |
| `TRUE_PEAK_DBTP` on final | ≤ -1.0 (lossy delivery) |
| `INTEGRATED_LUFS` | the user's spec, or the table in SKILL.md |
| `LRA_LU` | genre-dependent. Report it; don't "fix" it unasked |
| `MONO_FOLD_LOSS_DB` | under about 3 dB. More means the mix falls apart on phones |
| `TOTAL_CLIPPING_EVENTS` | 0 |

Bounce:

```bash
$W run export master --output /abs/Song_Master_24b48k.wav --format wav --bit-depth 24 --range full --tail-ms 2000
$W run job status --id <job_id from reply>     # poll until done; report destination
```

For a 16-bit CD/MP3 source add `--bit-depth 16 --dither on`. Leave
`--normalize off` on a limited master: normalizing after limiting changes
true peak. If the master fails a check, report the measured numbers and
the likely fix (limiter ceiling, master gain) instead of re-exporting in a
loop.

## 10. Stems and deliverables

Example ask: *"Clean stems, instrumental, and the master."*

1. Confirm naming, sample rate, bit depth, dry/wet (`--print-sends`) and
   sidechain policy with the user, or state your defaults.
2. Stems: `export stems --output /abs/Song_Stems/ --track <ids> --format wav
   --bit-depth 24 --range full --tail-ms 2000`.
3. Instrumental: `track set-mute --track <vox ids> --on`, then
   `export master --output /abs/Song_Instrumental.wav --range full`,
   then **unmute** (`track set-mute --track <vox ids>`) and verify with
   `track list`. Leaving tracks muted is the classic mistake.
4. Poll `job list` until every job is complete and list the files
   delivered. Don't claim a file exists until its job says it's done.

## 11. Session hygiene: "prep this for mixing"

1. `snapshot`. Show the user the current state.
2. Propose, then run on approval: `track sanitize-names` (renames
   everything), `track auto-color`, bus creation and `route folder`
   groupings by name (`Kick*`, `Snare*`, `OH*`, `Tom*` → Drums; `Bass*`;
   `Gtr*`; `Keys*`/`Synth*`; `Vox*`/`BV*` → Vocals).
3. Gain staging (recipe 2).
4. FX returns: `Verb` and `Delay` auxes with post-fader sends at -18/-22 dB.
5. Final `snapshot`, plus a table: bus → members, aux → senders, per-track
   offset applied. Flag anything you couldn't classify instead of guessing.
