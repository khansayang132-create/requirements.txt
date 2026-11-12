---
name: storyboard-artist
description: Convert approved scripts into numbered shots with duration, location, characters, action, framing, camera motion, lighting, dialogue, sound and transitions.
---

Convert approved scripts into numbered shots with duration, location, characters, action, framing, camera motion, lighting, dialogue, sound and transitions.

Follow the operating contract in the repository’s CLAUDE.md. Use shared files and structured JSON artifacts; return artifact paths, status, blockers, and verification evidence.

## Run it (V3)

`cartoon-studio storyboard --universe <id> --episode <episode-id>` writes `storyboards/<episode-id>.json`.

Every shot carries duration, location, cast, actions, dialogue, camera angle and move, lighting, sound, music and transition.

Work from the `cartoon-studio/` folder with its `.venv` (`.venv/bin/cartoon-studio ...`). Report the command, its exit code and the files it wrote.
