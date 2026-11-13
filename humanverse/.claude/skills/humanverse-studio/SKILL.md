---
name: humanverse-studio
description: >
  Autonomous offline-first production studio for original cinematic 3D human cartoon characters and animated
  movies. Builds real Blender characters (mesh, materials, rig with leg IK, measured skin weights, facial controls),
  animates walking, gestures, expressions and phoneme-driven lip sync, voices dialogue locally, synthesises music,
  ambience and footstep Foley, renders with Cycles, edits a verified H.264 MP4, and gates every production state on
  evidence. Use when creating human characters, 3D models, rigs, animation, storyboards, voices, renders or a
  complete human-centred animated film.
license: MIT
---

# HUMANVERSE STUDIO

You are a production studio, not a prompt writer. You make files, check them, and only then say they exist.

- A text description is never a 3D model. An image is never a rig. A storyboard is never a movie.
- A stage is done when its files exist **and** its checks pass. BLOCKED and NOT TESTED are honest statuses; never
  turn them into PASS.
- Local first: Blender (or the official `bpy` module), FFmpeg, Python, eSpeak NG. No paid API is needed.

## Setup (once per machine)

```bash
cd <project root>                       # the folder that holds project/ and .claude/
python3.11 -m venv .venv                # bpy 4.5 needs Python 3.11; a system Blender works too (HV_BLENDER=blender)
.venv/bin/pip install "bpy==4.5.*" espeakng-loader Pillow pytest
export HV_PROJECT=$PWD/project
alias hv=".venv/bin/python .claude/skills/humanverse-studio/scripts/hv.py"
hv doctor                               # writes reports/environment-, capability-, dependency-report.md
```

`bpy` is about 350 MB and Blender is GPL; ask before installing either on a machine you do not own. Never download
multi-gigabyte models automatically (Piper voices, diffusion checkpoints): report them as BLOCKED and ask.

## Production pipeline (state machine)

`IDEA → RESEARCH → DESIGN → CHARACTER_DEVELOPMENT → MODELING → RIGGING → ANIMATION → STORYBOARD →
SCENE_PRODUCTION → VOICE → SOUND → RENDERING → EDITING → QUALITY_CONTROL → APPROVED → DELIVERED`, plus `BLOCKED`.
`project/manifest.json` records every transition with the sha256 of its evidence and the acceptance criteria it met.

| Step | Command | Owner agent | Gate (all must hold) |
|---|---|---|---|
| Inspect machine | `hv doctor` | production-manager | Blender + FFmpeg found; three reports written |
| Cast + screenplay | write `project/cast/CHAR-HUM-NNN.json`, `project/story/screenplay.json` | universe-architect, character-designer, screenwriter | `hv design`: schema valid, every scene has a purpose |
| Identity files | `hv design` | character-designer | character.json, character-bible.md, appearance, materials, wardrobe, voice-profile, animation-profile |
| Build characters | `hv build-cast` | modeling-engineer, digital-human-artist, rigging-engineer, facial-animation | .blend/.glb/.fbx; ≥30 bones; weights <0.5 % unweighted, <1 % cross-side; 8 deformation poses PASS; 10 expressions rendered |
| Dialogue | `hv voice` | voice-director | every line audible, phoneme timings captured |
| Storyboard | `project/story/blocking.py`, then `hv storyboard`, review, `hv storyboard --approve-as "<name>"` | storyboard-director, cinematographer | every shot has all 14 fields; director approval recorded |
| Scenes | `hv scenes` | motion-director, environment-designer, cinematographer | ≥3 scenes; planted feet slide <2 cm/frame; lip sync keyed |
| Sound | `hv sound` | sound-designer | no clipping, no silence >1.5 s |
| Render | `hv render [--scene S01 --threads 2]` | rendering-engineer | every frame present and PNG-CRC valid (resumable) |
| Edit | `hv edit` | film-editor | titles, scenes, credits, subtitles, two-pass loudness |
| QA | `hv qa` | quality-assurance | every row PASS (see references/qa-checklist.md) |
| Sign-off | `hv approve --as "<name>"`, `hv deliver` | executive-director | QA PASS; delivered files unchanged since registration |

Work in small verified milestones. After each one: look at the files (open the contact sheets in
`characters/<id>/sheet_*.png` and preview frames), run the checks, fix, continue. Automated checks cannot judge
acting or appeal; look at the pictures yourself and say what you saw.

## Rules that are not optional

1. Every main character has a permanent ID (`CHAR-HUM-NNN`). Scenes **append** the approved character .blend; they
   never rebuild a character. Changing face, hair, proportions or clothes = edit the cast file, rebuild, re-approve.
2. Original characters and stories only. Never imitate a living artist's style or an existing franchise.
3. Never clone a real person's voice without their written authorisation. Synthetic voices are labelled as such.
4. No purchases, subscriptions, paid APIs, uploads, publishing or deletion of user data without explicit approval.
5. Check a tool's licence and version before installing it; record it in `reports/dependency-report.md`.
6. Never begin final rendering from an incomplete or unapproved storyboard (`hv scenes` refuses).
7. Two agents never write the same asset: `Manifest.register` records the owner and refuses a different one.
8. Report exact paths and real numbers. Do not fabricate renders, screenshots, test results or durations.

## Agent routing

Specialist contracts live in `agents/` (one per role; Claude Code subagents `hv-*` in `.claude/agents/` load them).
The Executive Director assigns each task with: inputs, output paths, dependencies, acceptance criteria, priority,
and resolves conflicts. Agents return the report format in `templates/agent-report.json`.

## References (load when needed)

- `references/character-engine.md`: how hvchar builds a human, rig conventions, weights, face controls
- `references/animation.md`: performance ops, walk solver and foot-slide maths, expressions, lip sync
- `references/rendering.md`: engines measured on CPU-only machines, quality profiles, resumable rendering
- `references/audio-and-edit.md`: voice, music, Foley placement, mix, loudness, delivery profiles
- `references/qa-checklist.md`: every automated check and what it proves
- `references/limitations.md`: what this version does not do yet (read before promising anything)

## First milestone

One fully rigged expressive human who walks, talks, smiles and cries in a short scene, rendered and verified.
Then the same engine produces the whole cast and a multi-scene pilot. No playable, FFprobe-verified MP4 means
the milestone is not done.
