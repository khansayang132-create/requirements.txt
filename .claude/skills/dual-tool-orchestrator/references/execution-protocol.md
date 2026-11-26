# Execution protocol

## State

Keep one state file per run, `<scratchpad>/orchestrator-run.json`, and update it after every step:

```json
{"task": "voiceover for auto-2026-11-26", "started": "<ISO time>",
 "steps": [
   {"step": "tool1.read_plan", "status": "ok", "evidence": {"doc_id": "auto-2026-11-26", "version": 1, "scenes": 7}},
   {"step": "transfer", "status": "ok", "evidence": {"draft": "draft.json", "flagged": 4, "rewritten": 4}},
   {"step": "tool2.render", "status": "failed", "attempt": 1, "error": "exit 2: scene 5 still has a [placeholder]"},
   {"step": "tool2.render", "status": "ok", "attempt": 2, "evidence": {"duration_s": 45.65, "lufs": -14.23}}
 ],
 "result": {"file": "voiceover.mp3", "ffprobe": {"codec": "mp3", "duration": 45.67}}}
```

Statuses: `ok`, `failed`, `skipped` (with the reason), `blocked` (a missing tool or permission).

## Steps

1. **Analyse.** Resolve the plan id (today in Asia/Karachi unless named), the engine and the output path.
   Write the first state entry.
2. **Prepare (parallel with step 3 when installs are needed).** Repo checked out with `nova/`; venv ready;
   `ffmpeg` present. Record what was installed.
3. **TOOL_1.** Read the plan with `out_dir`. Validate (see verification rules). On "No document", record
   `blocked: no plan yet` and stop: there is nothing to transfer.
4. **Transfer.** Run `scripts/transfer.py`; rewrite flagged lines; save the final list; confirm no `[`.
5. **TOOL_2.** Render. Parse the last stdout line as JSON. Validate the file with `ffprobe`.
6. **Report.** Use the report format in `SKILL.md`, with values copied from the state file.

## Retries and recovery

| Failure | Recoverable? | Action |
|---|---|---|
| TOOL_2 exit 2, placeholder left | yes | rewrite that line, run once more |
| TOOL_2 exit 2, empty or malformed list | yes | rebuild the list from the saved plan file, run once more |
| Network error while installing or downloading weights | yes | retry once after 30 s |
| `No document` from TOOL_1 | no | stop: report that the plan is not written yet |
| ArtifactData or `nova/` missing | no | stop: report the missing tool, never simulate it |
| The same failure twice | no | stop with both error messages |

At most one retry per step. Keep successful outputs (plan file, final list, partial logs) when stopping.
Never change the Studio database, scheduled tasks or credentials as part of recovery.
