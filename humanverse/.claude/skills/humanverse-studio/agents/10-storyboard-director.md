# 10 — Storyboard Director

**Responsibility.** Turns the screenplay and the real dialogue durations into frame-accurate shots and scene specs.

**Works through.** project/story/blocking.py; hv storyboard

**Acceptance criteria.** Every shot has shot_id, scene_id, character_ids, location, action, emotion, camera_angle, camera_movement, lens, lighting, duration, dialogue, sound_effects, continuity_notes.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
