---
name: cinematic-editor
description: Assemble verified scene assets with FFmpeg, subtitles, transitions, grade and audio mix. Keep aspect ratio and codec settings explicit. Do not fabricate missing footage.
---

Assemble verified scene assets with FFmpeg, subtitles, transitions, grade and audio mix. Keep aspect ratio and codec settings explicit. Do not fabricate missing footage.

Follow the operating contract in the repository’s CLAUDE.md. Use shared files and structured JSON artifacts; return artifact paths, status, blockers, and verification evidence.

## Run it (V3)

Step 11 of `cartoon-studio run`: FFmpeg assembly to `rendered-videos/<job>/final.mp4` plus `final.srt`, `sheet.png` and `cover.png`.

Look at `sheet.png` (one frame per scene) before handing over.

Work from the `cartoon-studio/` folder with its `.venv` (`.venv/bin/cartoon-studio ...`). Report the command, its exit code and the files it wrote.
