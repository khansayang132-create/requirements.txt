---
name: digital-human-factory
description: Produce talking-presenter / digital-human videos with the dhfactory Python package in digital-human-factory/ (HeyGen, Synthesia, D-ID, ElevenLabs, Runway, Higgsfield adapters, typed agents, resumable pipeline, QC). Use when asked for a digital human, AI presenter, talking avatar, or to run/check/resume a presenter video job.
---

# Digital human factory

Work from `digital-human-factory/` with its venv (`make install` once).

1. `.venv/bin/dhfactory doctor`: see which providers are PASS / BLOCKED. Don't select a BLOCKED provider for a live run.
2. Write the script to `scripts/<name>.txt`. Characters are fictional (`configuration/presenter.json`); a real person's
   likeness needs `character.likeness_consent`, and a cloned voice needs `configuration/voice-authorizations.json`.
3. `dhfactory init-job --script scripts/<name>.txt --job <id> --avatar <heygen|synthesia|did|mock> --voice <elevenlabs|mock> [--video runway|higgsfield|none]`
4. `dhfactory run --job <id>`: free steps run; paid steps stop as `blocked_pending_approval`.
   Only add `--approve-spend` after the owner approves the estimate in this conversation. Never on your own.
5. Read `jobs/<id>/production_report.json` and `rendered-videos/<id>/qc_report.json`. Report each step with its status word
   (PASS / FAIL / BLOCKED / NOT_TESTED). A mock-made video is never a delivered presenter.
6. Interrupted? Run the same `run` again; it resumes and reuses paid provider job ids.

Status and limits: `digital-human-factory/documentation/installation-report.md`.
