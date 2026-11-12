---
name: cartoon-production
description: Orchestrate original cartoon universe and episode production with character-bible consistency, provider approval gates, FFmpeg assembly, and evidence-based QC.
---

# Cartoon Production Workflow

1. Read `CLAUDE.md`, `documentation/provider-matrix.md`, and the selected universe/character bibles.
2. Validate universe and character bible; verify reference hashes before storyboarding.
3. Write structured episode JSON and storyboard JSON before generating media.
4. Generate each scene separately with stable character references and deterministic asset naming.
5. Confirm credentials and pricing/credits. Stop paid work until explicit approval.
6. Generate voice and sound assets with licensed voices and original/cleared music.
7. Assemble with FFmpeg; retain source clips and manifests.
8. Run visual inspection, ffprobe and decode tests; write QC report with PASS/FAIL/BLOCKED/NOT TESTED.
9. Never label a text-only demo or motion-comic as full 3D animation.

## Commands (V3, local engine, no spend)

```bash
cd cartoon-studio
.venv/bin/cartoon-studio doctor                                      # what is PASS / BLOCKED
.venv/bin/cartoon-studio import-universe --id mosslight-valley       # or: init-universe --concept "..."
.venv/bin/cartoon-studio init-characters --universe mosslight-valley # bibles + hash locks; look at the sheets
.venv/bin/cartoon-studio write-episode --universe mosslight-valley --plot seed-glow --seconds 60
.venv/bin/cartoon-studio run --job <job> --universe mosslight-valley --episode mosslight-valley-seed-glow-1
.venv/bin/cartoon-studio qc --video rendered-videos/<job>/final.mp4
```

Paid providers run only with `--video-provider <name> --approve-spend`, after the owner has approved the provider, the model and the maximum cost.
