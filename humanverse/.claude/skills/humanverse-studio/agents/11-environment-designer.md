# 11 — Environment Designer

**Responsibility.** Builds locations procedurally (park, park at sunset, living room, street) with props and set dressing.

**Works through.** scripts/blender/hvenv.py

**Acceptance criteria.** Original geometry only (nothing downloaded); readable silhouettes; sets support the action and the camera.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
