# Test results

Run 2026-11-26 (UTC) in the cloud sandbox. TOOL_1 = `ArtifactData` (LSKhan Studio database, read only),
TOOL_2 = `python -m nova.daily` (NOVA renderer). Every result below was produced by an actual run.

| Test | What ran | Result |
|---|---|---|
| 1. TOOL_1 alone | `ArtifactData get plans/auto-2026-11-25` with `out_dir` | PASS: file saved, version 1, type Lucu, 7 scenes, 14 placeholders |
| 2. TOOL_2 alone | `nova.daily` on a one-scene list, engine `piper` | PASS: exit 0, mp3, 2.66 s (ffprobe), -14.09 LUFS, true peak -1.0 dBTP |
| 3. TOOL_1 → TOOL_2 | `scripts/transfer.py` on that plan (7 scenes, 4 flagged), flagged lines rewritten to general statements, then `nova.daily` | PASS: exit 0, mp3 48 kHz, summary 45.68 s vs ffprobe 45.72 s, -14.21 LUFS |
| 4. Recoverable failure | the unrewritten draft passed straight to TOOL_2 | PASS: TOOL_2 refused with exit 2, `error: scene 3 still has a [placeholder]`; after rewriting, the re-run succeeded (test 3) |
| 5. Evidence from both | report built from TOOL_1 (`auto-2026-11-25`, version 1, 7 scenes) and TOOL_2 (summary + ffprobe) | PASS |

Also checked:

- Claude Code discovered the skill in the same session (it appeared in the available skills list); no
  restart was needed.
- `skills_manager.py audit`: `dual-tool-orchestrator` LOW, 0 findings.
- `skills_manager.py verify dual-tool-orchestrator --live`: FAIL "not in project registry". That check
  only applies to skills the manager installed from a git source; this skill is authored in the repo,
  like `design-check` and `artist-profile`.
- Engine used in tests 2-3 was `piper` for speed; the Chatterbox path was verified separately
  (`nova/STATUS.md`). A scheduled cloud run on Python 3.11 failed at `pip install` because
  `chatterbox-tts` needs numpy<2 there and NOVA pins numpy>=2 (open; the daily task is paused).
