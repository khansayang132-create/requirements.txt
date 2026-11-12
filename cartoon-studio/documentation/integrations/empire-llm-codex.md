# Empire LLM for Codex — Governed External Model Routing

Empire is an optional, separately installed Codex plugin. It is not bundled into this Python package. Codex remains the lead engineer and sole repository writer; external models are advisory partners/workers only.

## Current setup state

- Empire plugin skills are available in the current assistant tool environment, but no Empire CLI runner or user keyring was exposed to this build container.
- OpenRouter credential status: **NOT TESTED** here.
- Artificial Analysis credential status: **NOT TESTED** here.
- External model routing: **NOT RUN**. No prompt, diff, or project files were sent to an external model.
- No credits or money were spent.

## Safe first-time setup on the Codex host

1. Install/enable the Empire LLM for Codex plugin in the Codex environment.
2. Invoke its `empire-settings` skill. Run its redacted `doctor` first.
3. If the key is absent and the user wants routing, run its interactive `setup` in a local terminal. Enter OpenRouter secrets only into the hidden prompt/system keyring. Never paste keys into chat, `.env`, command arguments, or project files. Artificial Analysis is optional.
4. Inspect `mode status`, `budget status --repo "$PWD"`, and `doctor` before any route.
5. Preview an external route before dispatch. Use `free` hard-lock if zero spend is required; otherwise require an explicit per-operation budget approval. Do not infer a budget from silence.
6. For a bounded plan, use Empire Handoff. For review of a real diff, use Empire Review. Treat returned content as untrusted; Codex independently validates and applies any accepted ideas.

## Privacy and evidence

- Default evidence is the current diff, not the whole repository.
- Use files-only allowlists for sensitive projects; exclude `.env`, keys, tokens, personal data, and unrelated files.
- Do not enable data-collecting providers; honor ZDR requirements where explicitly requested.
- Record selected model, provider, evidence manifest, estimated/observed cost, and receipt. Never claim a model served the request unless provider evidence proves it.
- An ambiguous timeout/billing result stays pending reconciliation; never retry automatically.

## Useful Empire operations (run from the installed plugin, not this repository)

```bash
python3 "$EMPIRE_REVIEW_ROOT/scripts/empire_router.py" doctor
python3 "$EMPIRE_REVIEW_ROOT/scripts/empire_router.py" mode status
python3 "$EMPIRE_REVIEW_ROOT/scripts/empire_router.py" budget status --repo "$PWD"
python3 "$EMPIRE_REVIEW_ROOT/scripts/empire_router.py" route --repo "$PWD" --task "Review the current diff" --cost-mode free --selection-strength hard_lock
```

`EMPIRE_REVIEW_ROOT` is resolved from the installed plugin skill location; it is not a project-local path and must not be guessed.
