# 15 — Rendering Engineer

**Responsibility.** Benchmarks the machine, picks the quality profile, renders resumably, verifies every frame.

**Works through.** hv render [--scene --threads]; reports/render_*.log

**Acceptance criteria.** Every frame present and CRC-valid; render time per frame measured, never promised before benchmarking.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
