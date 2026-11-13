# 07 — Motion Director

**Responsibility.** Body animation: walking along paths with planted feet, idle breathing, waving, talking gestures, cheering, slumping, reaching, nodding, turning, looking.

**Works through.** performance ops in the scene spec (blocking.py); scripts/blender/hvanim.py

**Acceptance criteria.** Planted feet slide < 2 cm per frame (measured); no limb crossing into the body at rest; motion serves the beat.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
