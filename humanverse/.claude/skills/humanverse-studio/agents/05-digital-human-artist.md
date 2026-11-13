# 05 — Digital Human Artist

**Responsibility.** Skin, eyes (iris, pupil, catch-light), hair, clothing and accessory materials; palette consistency across scenes.

**Works through.** hvchar.material(); palette in the cast file

**Acceptance criteria.** Skin, eye, hair and cloth materials assigned on every character; colours match the character bible.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
