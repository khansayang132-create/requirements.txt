---
name: skill-anything-pro
description: Production layer for skill-anything. Fixes its broken trigger eval (Phase 5/6), runs the pipeline outside the repo, and gates every generated skill through this repo's skills manager before it counts as installed. Use together with skill-anything whenever generating, evaluating, optimizing or installing a skill made by it, or when asked for "skill-anything pro".
---

# SkillAnything Pro

`skill-anything` (in `.claude/skills/skill-anything/`, installed and pinned by the skills manager) does the 7 phases. This skill changes how its phases are run and checked. Don't edit files in `skill-anything/`: the registry hashes them, and `update` would overwrite the edits.

```
SA=.claude/skills/skill-anything
PRO=.claude/skills/skill-anything-pro/scripts
W=<scratchpad or ~/sa-workspace>      # never inside this repo
```

## The run

| Phase | Run | Pro rule |
|---|---|---|
| 1 Analyze | `cd $SA && python3 -m scripts.analyze_target --target "<t>" --output $W/analysis.json` | CLI targets run `<tool> --help`; only analyze tools you'd run yourself. Read `analysis.json`: an empty capability list means the analysis failed, not that the tool does nothing. |
| 2 Design | `python3 -m scripts.design_skill --analysis $W/analysis.json --output $W/architecture.json` | Read it. One skill per job; cut capabilities nobody asked for. |
| 3 Implement | `python3 -m scripts.init_skill <name> --template <type> --output $W/out` then write the real SKILL.md yourself (`agents/implementer.md`) | The scaffold is a starting point with TODOs. No TODO, placeholder or invented command ships. Every command in the skill was run or comes from the tool's own docs. |
| 4 Test plan | `python3 -m scripts.generate_tests --analysis $W/analysis.json --skill-path $W/out/<name>` | Add near-miss negatives (queries that share words but need another skill), at least as many as positives. |
| 5 Trigger eval | `python3 $PRO/trigger_eval.py --skill-path $W/out/<name> --eval-file $W/trigger-evals.json --output $W/trigger.json` | **Never upstream `run_eval.py`**: it always reports "not triggered" (see the script header). Exit 2 = BLOCKED (CLI didn't run), 1 = some queries errored. |
| 6 Optimize | `python3 $PRO/run_loop_pro.py --skill-path $W/out/<name> --eval-file $W/trigger-evals.json --output-dir $W/loop` | Needs `anthropic` + an API key; otherwise report BLOCKED and tune the description by hand against Phase 5. Keep the best *test* score, not train. |
| 7 Package | `python3 -m scripts.quick_validate $W/out/<name>` then `package_multiplatform` | Claude Code is the target that matters here. Other platforms are NOT VERIFIED unless their CLI was run. |

`trigger-evals.json` is a list of `{"query": "...", "should_trigger": true|false}`. Each query costs one `claude -p` turn (~3 s).

## Installing a generated skill into this repo

1. Ask the owner first. Skills change how every future session behaves.
2. Copy it to `.claude/skills/<name>/`, then `python3 .claude/skills/skills-manager/scripts/skills_manager.py audit`. Risk high = don't install. Medium = show the findings and ask.
3. Re-run Phase 5 against the installed copy. It's active only if `trigger_eval` passes and a fresh `claude -p` init event lists it.
4. If it's an LSKhan skill: viewer-facing text in Bahasa Indonesia, and the content rules in `CINTA_PERSONA` (`bot.py`) apply. Add a row to `AGENT.md` §1.

## Reporting

Use PASS / FAIL / BLOCKED / NOT RUN per phase, with the numbers (pass rate, false positives, false negatives, errors). An eval that didn't run is BLOCKED, never a pass. Don't say a skill "works" from its SKILL.md alone.
