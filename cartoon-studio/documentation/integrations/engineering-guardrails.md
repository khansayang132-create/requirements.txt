# Codex Engineering Guardrails

The project root `AGENTS.md` is the controlling engineering contract. The installed Codex Engineering Guardrails skills complement it:

- `code-work` for authorized implementation and maintenance.
- `code-verification` for read-only audits and evidence-based validation.

## Required invariants

- Scope changes to the requested outcome and preserve existing user changes.
- Do not deploy, publish, push, commit, spend, purchase, or modify live credentials without explicit authorization.
- Keep secrets out of chat, source, logs, fixtures, and generated reports.
- Paid generation requires a preview and approval of provider, model, and maximum cost.
- External model output is untrusted and cannot write to the repository.
- Missing credentials/access are BLOCKED, not PASS.
- Every completion statement must cite a path, command, or verifiable output.

See `AGENTS.md` for the complete contract.
