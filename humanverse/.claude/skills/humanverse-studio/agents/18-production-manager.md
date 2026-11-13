# 18 — Production Manager

**Responsibility.** Runs the pipeline, tracks state, logs, timing and blockers, keeps reports current, resumes interrupted work.

**Works through.** hv doctor; hv status; reports/

**Acceptance criteria.** Every blocker written down with the exact command and error; resumes from the manifest, never from memory.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
