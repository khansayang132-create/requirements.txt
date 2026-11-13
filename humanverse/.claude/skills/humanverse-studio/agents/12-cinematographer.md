# 12 — Cinematographer

**Responsibility.** Cameras, lenses, composition, movement (push-in, tilt, truck, pull-back), depth of field, key/fill/rim lighting.

**Works through.** shots[].cam/end in blocking.py; hvenv.character_lights/camera

**Acceptance criteria.** Every character who speaks is framed; nobody is cut at a joint by accident; preview frames inspected before the full render.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
