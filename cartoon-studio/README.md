# Cartoon Studio

Original cartoon universes, character bibles and finished episodes, made by ten agents in a 13-step resumable pipeline.

**V3.0** (this version) turns the v0.3 scaffold into a working studio. Pictures, voices, sound and the final MP4 come
from the local engine in `../wonderland-studio`: a 3D toon renderer (Three.js in headless Chromium) with a 2D fallback,
free voices (Kokoro or eSpeak), generated Foley and music, and an FFmpeg mix and edit. It is free and works offline.
Paid providers (Runway, FLUX, ComfyUI Cloud, Kling, Higgsfield, ElevenLabs) are optional extras, and each one is
BLOCKED until you add its key *and* pass `--approve-spend`.

What has really been run, and what is still blocked: `documentation/test-reports/demo-status.md`.

## Install

```bash
cd cartoon-studio
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e '.[test]'                          # add '.[providers]' only if you will use a paid provider
cp .env.example .env                              # keys stay in .env, never in git
cartoon-studio doctor
pytest -q
```

Needs `ffmpeg` on the PATH. The 3D look also needs Chromium with Playwright; without it the studio draws in 2D and says so.

## Make an episode

```bash
cartoon-studio import-universe --id mosslight-valley         # your v0.3 universe; your JSON files are not modified
cartoon-studio init-characters --universe mosslight-valley   # references, sheets, voices, sha256 locks
cartoon-studio write-episode --universe mosslight-valley --plot seed-glow --seconds 60
cartoon-studio run --job ep001 --universe mosslight-valley --episode mosslight-valley-seed-glow-1
cartoon-studio qc --video rendered-videos/ep001/final.mp4
```

For a brand-new world, run `cartoon-studio init-universe --concept "tiny friends who fix things" --seed 3`.
If a run stops partway, the same `run --job ep001` picks up where it left off.

| Step | Agent | Output |
|---|---|---|
| 01 universe | Creative Director | `universes/<id>/universe-bible.json` (your `universe.json` is never touched) |
| 02 character bibles | Character Designer | bible hash check; the job refuses to continue if any reference changed |
| 03–05 script, analysis, storyboard | Story Writer, Production Manager, Storyboard Artist | `stories/`, `scripts/`, `storyboards/` |
| 06, 08 backgrounds, animation | Animation Engineer | `scenes/<job>/backgrounds/`, `animations/<job>-silent.mp4` |
| 07, 10 voices, sound mix | Voice & Sound Engineer | voices, Foley (`sound-effects/`), music, mix at −14 LUFS |
| 09 external video (optional, paid) | Video Generation Engineer | skipped unless `--video-provider` and `--approve-spend` are given |
| 11 assembly | Cinematic Editor | `rendered-videos/<job>/final.mp4`, `.srt`, `sheet.png`, `cover.png` |
| 12 QC | Quality Control | `qc_report.json`: ffprobe, full decode, duration ±10 %, lip-sync track, bible hashes |
| 13 export | Production Manager | `jobs/<job>/production_report.json` |

The ten Claude Code subagents in `.claude/agents/` each say which command they own, and the `cartoon-production`
skill lists the commands in order.

## Character bibles

`character-bibles/<id>/` holds `character.json` (the canonical identity, written once and never overwritten),
`reference_front/side/back.png`, `expression_sheet.png`, `pose_sheet.png`, `color_reference.png`, `voice_id.txt`,
`turnaround.png` and `bible.json`. `bible.json` records the sha256 of every image *and* of `character.json`. If any of
those files change, every later job is blocked until the bible is approved again.

The engine draws five body plans: bunny, cat, elephant, duck and bear. Mosslight's moss rabbit, mushroom fox, pond
turtle, sun-moth and acorn badger are drawn as the closest free body plan. This is recorded in `visual.engine_body`
and listed as a warning, never hidden. True turtle or moth models need either a new engine model or an image provider
with the bible references.

## Rules the code enforces

* No paid call without `--approve-spend`, and never above `CS_MAX_SPEND_USD` (default $5) or without a confirmed price in `configuration/pricing.json`.
* A missing key means BLOCKED, never a quiet switch to another provider.
* Every script passes the engine's child-safety review and an originality check (famous characters, brands).
* QC says PASS only for a real file that probes *and* fully decodes. `visual_identity_review` stays NOT TESTED until someone has looked.

## Claude Code installation

In this repository the project lives at `cartoon-studio/`; Claude Code picks up its `CLAUDE.md`, subagents and skill when you work in that folder.


## Codex integration audit (v0.3.0)

Run `cartoon-studio integration-audit` to inspect local Codex/Claude CLI availability and repository integration readiness. The audit is read-only: it does not read credentials, call external models, spend credits, or mutate host settings. Use `--json` for machine-readable evidence.

The Codex Dev Workflows and Engineering Guardrails repository contracts are included under `AGENTS.md`, `.codex/`, and `documentation/integrations/`. Voice Notify requires a supported macOS/Windows Codex host and manual hook trust. Empire LLM requires its separately installed plugin, secure local keyring, and explicit route/budget authorization.

## Multi-style design engine (15 art styles)

`cartoon-studio design …` generates original casts in 15 distinct styles and renders every reference for real with the
studio's 3D renderer (Three.js in headless Chromium; no GPU, no paid service). Code: `src/cartoon_studio/design/`.

| Command | What it makes |
|---|---|
| `design styles` | The 15 styles and what each changes |
| `design build [--styles a,b] [--per-style 5]` | Per style: 5 original characters, each with transparent front / three-quarter / side / back PNGs, turnaround, expression sheet, proportions sheet (head-top, chin and ground lines from the rig), palette + clothing card, pose sheet and a 3000×2200 production character sheet; plus the style's environment concept and cast lineup. QC rejects failures, keeps them in `design-library/rejected/` and regenerates (max 3 tries per slot). |
| `design compare --character ID --styles a,b,c,d,e` | The same character (identity locked: species, colours, clothing, name) in several styles side by side |
| `design studio` | Web interface on 127.0.0.1:8770: style, species, age, body proportions, fur/belly/clothing colours, clothing piece, expression, animation pose, camera angle, lighting and environment selectors; Render and Compare-5-styles are real renders |

How styles differ (all data in `design/styles.py`): seven shading models in the renderer's toon shader (toon bands,
soft 3D, clay with a procedural thumb-pressed surface, two-tone storybook with paper grain, hard anime cel, hyperreal
micro-texture with sheen, sci-fi glowing fresnel), per-style head/body/eye proportions on the rig, outline thickness,
lighting, palettes, environment and post grade. Studio names in style titles describe a general look only.

QC (`design/qc.py`, all measured on the PNGs): files readable and high-resolution; real transparency; figure present,
not cut off, no black/garbage regions; turnaround views at one scale; front vs three-quarter colour histogram
correlation; mirror symmetry (bows are one-sided by design); head:body ratio from the rig's anchors; spec colours present
(CIELAB distance); style actually applied (render mode recorded, outlines on bold-outline styles, texture on textured
styles, glow on sci-fi). Not measured by machine: appeal and acting; the sheets are made for a person to review.

Species are the studio's five rigs (bunny, cat, elephant, bear, duck). Human characters come from HUMANVERSE (Blender)
and are not part of this engine.

### Library verification (2026-11-13)

| Check | Result |
|---|---|
| Every file in `library.json` present, readable, sha256-identical | **PASS** — 825 / 825 files |
| Current QC re-run on every accepted character | **PASS** — 75 / 75 characters, 15 / 15 styles |
| Names unique across the library and the existing cast | **PASS** |
| Human review of all 15 lineups (`design-library/previews/*style_lineup.jpg`) | **PASS** — every character whole, no clipping or broken geometry, style visibly applied |
| Style comparisons (`previews/comparisons__*.jpg`: elephant, bear, bunny × 5 styles) | **PASS** — identity (palette, collar, markings) held; an elephant ear touching the panel edge was fixed by shrink-to-fit |

Known limit: every style draws on the same five species rigs, so styles differ in shading, palette, proportions and
accessories, not in new silhouettes. Appeal remains a person's judgement.

## Episode verification

Every packaged episode now gets `agency/media_audit.py`: all frames decoded (black, blank, frozen, flash), audio
(silence, per-channel clipping, EBU R128), and a real playback in Chromium, plus contact sheets in
`agency/out/production/episodes/<job>/review/`. An episode is PASS only if that audit passes as well as the studio QC.

| Episode | Story | Frames | Loudness / true peak | Playback | Notes |
|---|---|---|---|---|---|
| ep003 | rainy-picnic | 1303 | −14.0 LUFS / −2.1 dBFS | PASS | |
| ep004 | runaway-kite | 1570 | −14.0 / −2.4 | PASS | superseded: the set label "Valley panorama" spoken in the first line; kite drawn twice during the hand-off |
| ep005 | nervous-drum | 1302 | −14.0 / −2.5 | PASS | reviewed frame by frame |
| ep006 | runaway-kite | 1557 | −14.0 / −2.4 | PASS | caption fixed; still has the double kite (rendered before that fix) |
| ep007 | runaway-kite | 1557 | −14.0 / −2.4 | PASS | **current version of this story**: caption and single-kite hand-off both fixed and checked frame by frame |
