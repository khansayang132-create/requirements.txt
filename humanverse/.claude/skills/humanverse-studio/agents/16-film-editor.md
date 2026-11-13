# 16 — Film Editor

**Responsibility.** Assembles title, scenes, credits; fades; colour pass; subtitles; two-pass EBU R128 loudness; delivery profile.

**Works through.** hv edit -> project/movie/*.mp4, subtitles.srt, edit_report.json

**Acceptance criteria.** H.264 + AAC, delivery resolution and fps, duration equals the edit, subtitles muxed.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
