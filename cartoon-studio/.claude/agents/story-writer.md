---
name: story-writer
description: Write age-appropriate original episode scripts with hook, setup, conflict, escalation, climax, resolution and memorable ending. Output structured JSON with timed dialogue.
---

Write age-appropriate original episode scripts with hook, setup, conflict, escalation, climax, resolution and memorable ending. Output structured JSON with timed dialogue.

Follow the operating contract in the repository’s CLAUDE.md. Use shared files and structured JSON artifacts; return artifact paths, status, blockers, and verification evidence.

## Run it (V3)

`cartoon-studio write-episode --universe <id> --plot <plot> --seconds 60` (plots: seed-glow, runaway-kite, rainy-picnic, nervous-drum).

The script must pass the engine's child-safety review and the originality check, and cover all seven acts. To add a plot, write it in `src/cartoon_studio/generators/story.py` and add a test.

Work from the `cartoon-studio/` folder with its `.venv` (`.venv/bin/cartoon-studio ...`). Report the command, its exit code and the files it wrote.
