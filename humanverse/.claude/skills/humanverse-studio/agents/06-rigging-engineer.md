# 06 — Character Rigging Engineer

**Responsibility.** Skeleton (41 bones), leg IK with knee poles, arm IK switch, hand/finger/thumb chains, eye/lid/brow bones, face-control bone driving mouth shape keys; weights and deformation tests.

**Works through.** hv build-cast (build_report.json: skinning, deformation)

**Acceptance criteria.** Bone heat weights measured: unweighted < 0.5 %, cross-side leakage < 1 %; deterministic fallback recorded if used; 8 deformation poses PASS and rendered.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
