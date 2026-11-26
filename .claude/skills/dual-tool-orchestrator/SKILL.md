---
name: dual-tool-orchestrator
description: Coordinates two available tools to execute tasks, transfer outputs, manage failures, and verify completed operations. In this repo the pair is ArtifactData (reads the LSKhan Studio plan) and NOVA's renderer (python -m nova.daily, makes the voiceover). Use when a task needs one tool's output fed into another, e.g. "make a voiceover of today's LSKhan plan", or when asked to run, test or report a two-tool workflow with evidence.
---

# Dual-tool orchestrator

One agent, two tools, one result. Read a tool's output, check it, hand the right part to the second
tool, check that too, and report only what the evidence shows.

## The two tools (registered from what this environment actually has)

| | TOOL_1 | TOOL_2 |
|---|---|---|
| Name | `ArtifactData` (built-in; load with ToolSearch `select:ArtifactData`) | NOVA renderer: `python -m nova.daily` (run with Bash in `nova/`) |
| Purpose | Read the LSKhan Studio plan the "LSKhan daily video plan" task writes | Render scenes into one mastered voiceover (MP3/WAV) |
| Input | `action:"get"`, `url`, `collection:"plans"`, `doc_id:"auto-YYYY-MM-DD"` | `--segments today.json --out file.mp3 [--engine] [--speed] [--pause-scale] [--lufs]` |
| Output | Plan document (`plan.title`, `plan.type`, `plan.scenes[]` with `t`, `say`, `text`), `version` | Last stdout line: JSON summary (`out`, `engine`, `duration_s`, `lufs`, `true_peak_dbtp`, `scenes`); exit 0 |
| Errors | `No document …` (no plan yet), connector or permission errors | exit 2 with `error: …` (bad input, a line still holding a `[placeholder]`), exit 1 on engine failures |
| Limits | Read only here: never write to the Studio database | Chatterbox needs `requirements-neural.txt` and Hugging Face access; ~5 min on 4 CPUs |

Full schemas and the transfer mapping: [references/tool-coordination.md](references/tool-coordination.md).
If either tool is missing (no ArtifactData, no `nova/`), stop and report which. Never simulate one.

## Workflow

```
request → analyse → TOOL_1 (read plan) → validate → transfer (scripts/transfer.py + rewrite flagged lines)
        → TOOL_2 (render) → validate (summary + ffprobe) → report with evidence from both
```

1. **Analyse.** Which plan (today in Asia/Karachi unless named), which engine, output path. Steps that do
   not depend on each other (installing NOVA, reading the plan) may run in parallel.
2. **TOOL_1.** `ArtifactData get` with `out_dir` so the plan lands as a JSON file. Validate: the document
   exists and has a non-empty `plan.scenes`.
3. **Transfer.** `python3 .claude/skills/dual-tool-orchestrator/scripts/transfer.py <plan.json> <draft.json>`
   builds the scene list and flags every line holding a `[placeholder]`. Rewrite each flagged line yourself
   into a general true statement or an honest question; never invent personal facts or anything the husband
   said. Save the final list. See the rules in the coordination reference.
4. **TOOL_2.** Run `nova.daily` with the final list. Validate the JSON summary, then `ffprobe` the file.
5. **Report** in the format below. Steps, retries and state: [references/execution-protocol.md](references/execution-protocol.md).
   What counts as evidence: [references/verification-rules.md](references/verification-rules.md).

## Failure handling (summary)

- Recoverable: TOOL_2 exit 2 for a placeholder (rewrite the line, run again), a transient network error
  (retry once), a missing install (install, retry once).
- Not recoverable: no plan for the day, a missing tool, a second identical failure. Stop and report the exact
  error; keep every output that did succeed (the plan file, the draft list).
- Never loop: at most one retry per step.

## Report format

```
TASK: <what was asked>
TOOL 1: <status> — <doc_id>, version <n>, <k> scenes, <p> placeholders
TOOL 2: <status> — engine <e>, <duration>s, <lufs> LUFS, exit <code>
VERIFICATION: <ffprobe codec/duration; summary matches; no "[" in the spoken text>
FINAL RESULT: <file path, what was delivered>
BLOCKERS: <none, or the exact error>
```

Test log for this skill: [TEST_RESULTS.md](TEST_RESULTS.md).
