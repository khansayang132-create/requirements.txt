# AURAVOX X

A local voice production machine: character voices, multi-take dialogue with objective quality checks and a
bounded retry loop, a persistent crash-safe job queue, mixing and mastering, lip-sync data, a control centre, a
skills installer for Claude Code and Codex, and a handoff to HUMANVERSE's Blender pipeline.

No paid APIs. Engines: **eSpeak NG** (verified here) and **Piper** (code complete; its voice models come from
huggingface.co, which this sandbox cannot reach, so Piper is BLOCKED here and proven by CI instead).

```bash
cd auravox
uv venv .venv && uv pip install -e ".[piper,test]"
export AVX_HOME=$PWD/data
avx doctor                                        # environment + engine health from real speech -> data/reports/
avx voices from-humanverse ../humanverse/project/cast && avx voices select-cast --by "Your Name"
avx produce demo/gate2_conversation.txt --name gate2 && avx work
avx serve                                         # control centre on http://127.0.0.1:8765
```

## What is where

| Part | File |
|---|---|
| Database (jobs, tasks, voices, takes, models, engines, pronunciations, skills, prefs, events) | `src/auravox/db.py` |
| Engines and the common adapter (generate, generate_dialogue, analyze, align, convert, validate, export) | `src/auravox/engines/` |
| Capability router (health, language, timing, emotion, licence; never substitutes silently) | `src/auravox/router.py` |
| Model manager (catalogue, MD5 + size check, resumable download, approval threshold, licence) | `src/auravox/models.py` |
| Technology registry (17 technologies, sources, licences, hardware) | `src/auravox/registry.py` |
| Character voice factory (briefs, auditions, F0-separated cast, approval lock) | `src/auravox/voices.py` |
| Performance direction (emotion table, emphasis, pauses, takes, corrections) | `src/auravox/perform.py` |
| Screenplay → dialogue production, speaker-substitution guard | `src/auravox/production.py` |
| Audio intelligence (metrics, defect codes, fixes) | `src/auravox/analysis.py` |
| Queue (priorities, dependencies, leases, retries, pause/resume/cancel, memory guard, crash recovery) | `src/auravox/queue.py` |
| Lip sync (visemes, curves, validation report) | `src/auravox/lipsync.py` |
| Music, ambience, effects, mix, loudness master | `src/auravox/master.py` |
| Skills installer (scan, provenance, backup, install, host test, rollback) | `src/auravox/skills.py` |
| Control centre (live DB state, job controls, audio, export) | `src/auravox/server.py` |
| Gate 4 demo (Blender lip-synced MP4) | `demo/gate4/gate4.py` |
| 21 agents (Claude Code + Codex) | `tools/gen_agents.py` → `.claude/agents/`, `.codex/agents/` |
| Skill | `.claude/skills/auravox/SKILL.md` |

Evidence and status per milestone: [`docs/milestones.md`](docs/milestones.md).
