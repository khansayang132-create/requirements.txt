# AURAVOX X — milestones and gates

Statuses are PASS, FAIL, BLOCKED or NOT TESTED. Each row names the evidence; paths are relative to `auravox/`.
Machine: 4 CPU cores, 15 GB RAM, no GPU. Network: PyPI reachable; huggingface.co and GitHub release downloads
blocked in this sandbox (they are reachable from GitHub Actions).

## Gates (in order)

| Gate | Status | Evidence |
|---|---|---|
| 1. Working local engine | PASS | `avx doctor` → `data/reports/engines.md`: eSpeak NG spoke and was measured (114 languages). Indonesian line: 4.03 s, 40 engine phonemes, duration ratio 1.03. Router picked eSpeak for id/female/sad, rejected `tlh` (no such language) and Piper (BLOCKED), no substitution. |
| 2. Three distinct voices + full conversation | PASS | 5 voices from the HUMANVERSE cast, 3 auditions each, approved with profile hashes; F0 285.7 / 115.7 / 233.0 / 92.0 / 194.3 Hz, minimum separation 0.199, no duplicate variants. Production `gate2`: 6 lines, 3 speakers, 2 scenes; jobs AVX-JOB-000001…010 succeeded (`docs/evidence/gate2_queue.txt`). Lip-sync report PASS (correlation 0.40–0.66, end offsets ≤ 0.09 s). Master −16.09 LUFS, true peak −1.5 dBTP (`data/productions/gate2/master_report.json`, `master.mp3`). |
| 3. Queue, evaluation, retry, resume after restart | PASS | `tests/test_queue.py`: a worker process is SIGKILLed mid-job and a new worker recovers the expired lease and finishes; retries with back-off; dependency failure blocks dependants; pause/resume/cancel; memory guard; state survives reopening the database. Real use: the gate2 lip-sync job failed (pause-marker bug), was fixed and resumed with `avx queue retry`. 20 tests pass (`docs/evidence/pytest.txt`). |
| 4. Blender lip-synced dialogue → playable MP4 | see Milestone J/L | `demo/gate4/gate4.py`, `data/gate4/gate4_report.json` |

## Milestones

| | Milestone | Status | Evidence / limits |
|---|---|---|---|
| A | Environment inspection and capability report | PASS | `data/reports/environment.md` (OS, Python, CPU cores, free memory, GPU: none detected, free disk, ffmpeg). Network reachability was measured by hand (curl) and is recorded at the top of this file, not in the report. |
| B | Voice technology discovery and registry | PASS | `src/auravox/registry.py`: 17 technologies with source, licence, weights, hardware, limits; `data/reports/technology-registry.md`. Discovery recommends; it never auto-installs. |
| C | Skills installer and validator | PASS (Claude Code) / NOT TESTED (Codex host) | `src/auravox/skills.py`: dangerous-operation scan, front-matter validation, provenance (git commit, remote, dirty), backup, refusal without `--replace`, rollback. Real install of `humanverse-studio` into a fresh project; `claude -p` listed it (invocation PASS). Codex files are written and rolled back in tests; the Codex CLI is not installed here, so its invocation is NOT TESTED. |
| D | At least one verified local voice engine | PASS (eSpeak NG here; Piper in CI) | eSpeak NG via its C API with phoneme events. Piper: BLOCKED in this sandbox (huggingface.co unreachable), PASS on GitHub Actions run 43383376795 (`tools/ci_piper.py`): `en_US-lessac-low` downloaded (63,206,176 bytes, MD5 + size checked, sha256 f7d01dde…f375), engine health PASS, 2.48 s of speech, no defects, 48 engine phoneme alignments, lip-sync validation PASS (correlation 0.358, offsets -0.042 / +0.23 s). Licence recorded from the model card (Lessac Blizzard 2013 licence); not marked commercially usable. The first CI run found two real faults, both fixed: no alignments (needs `piper-tts[alignment]`) and 0 dBFS clipping (now -1 dBFS peak). |
| E | Unified voice generation API | PASS | `engines/base.py`: generate, generate_dialogue, analyze, align, validate, export; `convert` raises `Unsupported` (no engine here does speech-to-speech; not claimed). Router test: no silent substitution. |
| F | Character voice factory | PASS | `voices.py`: brief from a HUMANVERSE character, auditions, cast selection by F0 separation, approval with who/when/profile hash/model version; tampering raises `VoiceLocked`; `redesign` needs a person and a reason. |
| G | Multi-speaker dialogue production | PASS | `production.py`: screenplay → job graph; per line 3 takes + corrective regeneration, best take selected, rejected kept; speaker-substitution guard (voice id + profile hash + file hash) tested. |
| H | Audio intelligence and quality control | PASS | `analysis.py`: 12 defect codes, each with a fix; objective metrics kept apart from subjective notes. Tests: clean speech no defect, hiss flagged, clipping, silence, cut-off. |
| I | Persistent queue and recovery | PASS | See Gate 3. |
| J | Blender lip-sync integration | PENDING | Gate 4 render in progress. |
| K | Production control center | PASS | `avx serve` (`server.py`): live DB/system state, pause/resume/cancel/retry, worker start, audio playback, export zip; `tests/test_server.py` drives the real endpoints; design-check 0 errors at 390/1440 px light/dark (`.claude/design-log.md`). |
| L | End-to-end cartoon dialogue demonstration | PENDING | Gate 4 render in progress. |

## Agents

21 agents generated by `tools/gen_agents.py`: `.claude/agents/avx-*.md` (Claude Code) and `.codex/agents/avx-*.toml`
(Codex). Claude Code host check: `claude -p` run in `auravox/` listed all 21 `avx-*` subagents — PASS. Codex host:
NOT TESTED (CLI not installed here); the TOML files parse and contain exactly name, description, developer_instructions.

## Known limitations

- Piper voices: BLOCKED in this sandbox (network); verified on GitHub Actions, where the model can be downloaded.
- eSpeak NG sounds robotic; it is the honest baseline, not a production-grade voice.
- No voice cloning or speech-to-speech engine is installed; none is claimed.
- Perceptual quality (naturalness, acting, lip-sync as watched) is NOT TESTED by any automated check here.
