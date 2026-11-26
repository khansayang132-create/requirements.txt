# Verification rules

A step is `ok` only when its evidence is in hand. "The command ran" is not evidence.

## After TOOL_1 (ArtifactData)

- The result names a saved file, and that file parses as JSON.
- `plan.scenes` is a non-empty list and at least one `say` is non-empty.
- Record `doc_id`, `version`, the scene count and the placeholder count.

## After the transfer

- One entry per scene with a spoken line; labels match the plan's `t` values in order.
- No entry still contains `[` or `]`; no entry holds on-screen text, arrows or emoji.
- Every flagged line was rewritten into a general statement or a question; none claims a personal fact
  or quotes the husband. List the rewritten lines in the report.

## After TOOL_2 (nova.daily)

- Exit code 0, and the last stdout line parses as JSON with `out`, `duration_s`, `lufs`.
- `ffprobe` on `out`: an audio stream exists, the codec matches the extension, and the duration is within
  0.2 s of `duration_s`.
- `lufs` within 1 LU of the target (default -14) and `true_peak_dbtp` at or below -0.9.

## The final report

- Contains evidence from **both** tools: TOOL_1's `doc_id` and `version`, TOOL_2's summary values and the
  ffprobe result.
- States every failure and retry that happened, with the actual error text.
- Never reports a file that was not verified, and never sends a broken or partial file.
