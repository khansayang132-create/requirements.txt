# Workflow 03: recovery

- `hv status` shows the state and every transition with its note.
- BLOCKED: the history entry says why; fix it and re-run the same command (it resumes at the blocked state).
- Interrupted render: re-run `hv render`; only missing or CRC-corrupt frames are rendered again.
- A gate failed (e.g. "foot_slide_under_2cm (worst 2.11)"): read the measured numbers in the scene report,
  diagnose with a per-frame trace, fix the cause, rebuild. Never relax a gate to make it pass.
- `hv deliver` refuses if any registered asset changed after registration (sha256 mismatch).
