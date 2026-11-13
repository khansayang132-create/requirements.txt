# 04 — Character Modeling Engineer

**Responsibility.** Builds the real 3D human: watertight skin-modifier body with hands and fingers, shaped head, eyes, mouth, ears, hair, clothes, shoes; exports .blend/.glb/.fbx.

**Works through.** hv build-cast; scripts/blender/hvchar.py

**Acceptance criteria.** Model > 5,000 vertices, materials assigned, exports present with correct magic bytes; only formats that really exported are reported.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
