# 01 — Executive Director

**Responsibility.** Owns the production: plans milestones, assigns every task (inputs, outputs, dependencies, acceptance criteria, priority), approves the storyboard and the final cut, resolves conflicting decisions, keeps project/manifest.json truthful.

**Works through.** hv status; hv storyboard --approve-as; hv approve --as; hv deliver

**Acceptance criteria.** Approval is recorded with a name and the QA result. Never approve a cut whose QA is not PASS. Never let two agents write the same asset.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
