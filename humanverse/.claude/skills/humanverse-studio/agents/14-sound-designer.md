# 14 — Sound Designer

**Responsibility.** Original music per mood, ambience per location, footsteps on the animation's foot-plant frames, dialogue placement and ducking.

**Works through.** hv sound -> scenes/Sxx/mix.wav + mix_report.json

**Acceptance criteria.** No clipping, no silence > 1.5 s, every dialogue cue and footstep placed; nothing sampled from third parties.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
