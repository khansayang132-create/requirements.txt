# Installation report

Build target: local ChatGPT execution container, NOT the user's Claude Code host.

- Python: Python 3.13.5
- pip: pip 25.1.1 from /opt/pyvenv/lib/python3.13/site-packages/pip (python 3.13)
- OS: Linux 6.18.57 x86_64
- FFmpeg: ffmpeg version 7.1.5-0+deb13u1 Copyright (c) 2000-2026 the FFmpeg developers
- FFprobe: ffprobe version 7.1.5-0+deb13u1 Copyright (c) 2007-2026 the FFmpeg developers
- Blender: bash: line 261: blender: command not found
- GPU: bash: line 261: nvidia-smi: command not found

This report records the actual build container only. It is not a report of the user's Claude Code machine.

## V3.0 build (2026-11-12, Claude Code cloud sandbox, not the owner's machine)

- Python 3.13.18 in `cartoon-studio/.venv`, installed with `pip install -e '.[test]'` (uv)
- ffmpeg version 6.1.1-3ubuntu5 Copyright 
- Blender: not installed. GPU: none. Chromium + Playwright: present, so the 3D toon renderer is used.
- Provider hosts were blocked by this sandbox's network proxy and no keys exist, so every paid provider is BLOCKED and NOT TESTED live.
- Local engine: `../wonderland-studio` (override with `WONDERLAND_ROOT`).
