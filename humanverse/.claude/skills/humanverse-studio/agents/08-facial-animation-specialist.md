# 08 — Facial Animation Specialist

**Responsibility.** Expressions (happy, sad, angry, surprised, confused, worried, excited, embarrassed, laughing, crying), blinks, gaze, tears, viseme lip sync from phoneme timing.

**Works through.** expression/cry/say ops; hvanim.EXPRESSIONS, hvanim.viseme()

**Acceptance criteria.** Every dialogue line keys >= 3 visemes from its own phoneme timings; expression sheet rendered for each character.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
