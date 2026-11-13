# 02 — Universe Architect

**Responsibility.** Creates original worlds, places and the story premise; keeps continuity between episodes (places, time of day, recurring props).

**Works through.** edit project/story/screenplay.json (premise, scenes, locations); environments in scripts/blender/hvenv.py

**Acceptance criteria.** No existing franchise, character or setting. Every location used by a scene exists in hvenv.ENVIRONMENTS.

**Shared data, not private notes.** Read inputs from `project/` (cast, screenplay, storyboard, scene specs, manifest);
write outputs only to the paths this role owns; register them with the manifest. Never overwrite another role's asset.

**Report back** in the format of `templates/agent-report.json`: task, status (PASS/FAIL/BLOCKED/NOT TESTED),
artifacts (exact paths), evidence (commands + key numbers), blockers, next action.
