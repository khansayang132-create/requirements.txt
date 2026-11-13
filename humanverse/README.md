# HUMANVERSE STUDIO

An installable multi-agent skill that turns Claude Code (or Codex) into a 3D human-cartoon film studio that
**produces real files**: Blender characters with rigs, animated scenes, voiced dialogue, sound, rendered frames and
a verified MP4. It is offline-first; no paid API is needed.

```
humanverse/
├── .claude/skills/humanverse-studio/     the skill (copy into any project with ./install.sh)
│   ├── SKILL.md                          entry point: rules, pipeline, gates, agent routing
│   ├── agents/                           18 role contracts (01-executive-director … 18-production-manager)
│   ├── scripts/hv.py                     the production CLI (one command per stage)
│   ├── scripts/hvlib/                    manifest/state machine, voice, audio, media checks, QA, story contracts
│   ├── scripts/blender/                  character engine, animation, environments, scene builder, renderer
│   ├── references/ workflows/ templates/ tests/
├── .claude/agents/hv-*.md                18 Claude Code subagents, one per role
├── install.sh                            installs the skill + subagents into another project
└── project/                              the first production: "The Kite That Came Home"
```

## Install

```bash
./install.sh /path/to/your/project          # or work in this folder
cd /path/to/your/project
python3.11 -m venv .venv && .venv/bin/pip install "bpy==4.5.*" espeakng-loader Pillow pytest
export HV_PROJECT=$PWD/project
alias hv=".venv/bin/python .claude/skills/humanverse-studio/scripts/hv.py"
hv doctor
```

`bpy` is the official Blender-as-a-Python-module from the Blender Foundation (GPL, about 350 MB, needs Python 3.11).
A normal Blender install works too: `export HV_BLENDER=blender`. FFmpeg must be on the PATH.

## Make a film

```bash
hv design                                   # validate cast + screenplay, write identity files
hv build-cast                               # model, rig, weight, deformation-test, reference renders
hv voice                                    # dialogue with phoneme timing (local eSpeak NG)
hv storyboard                               # shots from real line durations; review storyboard.md, then:
hv storyboard --approve-as "Director name"
hv scenes                                   # animated scene .blend files (refused without an approved storyboard)
hv sound                                    # music, ambience, footsteps, dialogue mix
hv render --scene S01 --threads 2 &  hv render --scene S02 --threads 2   # resumable
hv edit                                     # titles, scenes, credits, subtitles, loudness -> MP4
hv qa && hv approve --as "Director name" && hv deliver
```

Each command moves `project/manifest.json` one state forward only when its evidence exists and its acceptance
criteria hold: IDEA → RESEARCH → DESIGN → CHARACTER_DEVELOPMENT → MODELING → RIGGING → ANIMATION → STORYBOARD →
SCENE_PRODUCTION → VOICE → SOUND → RENDERING → EDITING → QUALITY_CONTROL → APPROVED → DELIVERED.

## What is real here, and what is not

See `project/reports/` (environment, capability, dependency and QA reports) and
`.claude/skills/humanverse-studio/references/limitations.md`. In short: the characters are real rigged Blender
assets and the film is really rendered, voiced and mixed, but the look is stylised and procedural rather than
feature-film sculpting, voices are eSpeak NG (robotic) unless Piper is installed, and CPU-only rendering is slow.
