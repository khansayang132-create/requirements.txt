# 09 — Screenwriter

**Responsibility.** Original human-centred screenplay: title, logline, audience, genre, theme, motivations, conflict, emotional progression, scenes with purpose, dialogue, ending.

**Works through.** project/story/screenplay.json (+ screenplay.md)

**Acceptance criteria.** hv design validates it; lines <= 16 words; every scene has a narrative purpose; continuity between scenes.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
