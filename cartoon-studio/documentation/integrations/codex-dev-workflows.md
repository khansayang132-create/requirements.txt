# Codex Dev Workflows

This repository includes a project-local Codex contract (`AGENTS.md`), five focused custom-agent definitions in `.codex/agents/`, and a project-local `.codex/config.toml` with bounded concurrency. These are repository assets; they do not install the Codex CLI or marketplace plugins.

## Recommended workflow

1. **New project / scope:** capture requirements, assumptions, non-goals, architecture, and acceptance criteria before broad implementation.
2. **Orchestrate:** split independent packages with exclusive file ownership; keep integration and final verification with the lead agent.
3. **Feature development:** implement one vertical slice, add meaningful tests, and verify before expanding scope.
4. **Bug investigation:** reproduce first, isolate root cause, add a regression test, then make the smallest fix.
5. **Comprehensive QA:** verify behavior, error paths, security, state, media, accessibility where applicable, and regressions.
6. **Pre-release review:** map each acceptance criterion to fresh evidence; list blockers and rollback considerations.

Use the installed Codex Dev Workflows skills when available: `new-project`, `orchestrate-work`, `feature-development`, `bug-investigation`, `comprehensive-qa`, and `pre-release-review`.

## Commands

```bash
pytest -q
python -m compileall -q src tests
cartoon-studio doctor
cartoon-studio agents
```

Do not claim that the plugin skills were installed on another machine merely because this repository contains these instructions.
