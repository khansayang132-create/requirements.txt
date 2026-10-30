# CLAUDE.md

Read [`AGENT.md`](./AGENT.md) first. It is the index for this repo: what each part is, where its source of truth lives, the hard rules, and the traps that have broken things before.

Before calling any page, app, artifact or UI change done, run the design-check loop in [`.claude/skills/design-check/SKILL.md`](./.claude/skills/design-check/SKILL.md), or hand it to the `design-director` agent. A design isn't finished until its rendered check passes.

HarnessFlow (an opt-in AI workflow pack) is installed in `.github/HarnessFlow/`. Its rules load below; they do nothing unless a request is a filled-in template from `.github/HarnessFlow/request_template/`.

@.github/HarnessFlow/CLAUDE.md
