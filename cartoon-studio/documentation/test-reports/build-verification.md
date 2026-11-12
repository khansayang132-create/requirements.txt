# Build verification (executed in ChatGPT’s isolated container)

- Package editable-install: PASS (`pip install --no-build-isolation --no-deps -e .`; dependency installation was skipped because this environment has no network access).
- Unit tests: PASS (2 passed).
- Ten agent class imports/instantiation: PASS (`cartoon-studio agents`).
- Offline universe/character bible/story/storyboard generation: PASS (`cartoon-studio init-demo --output .`).
- FFmpeg: PASS (`/usr/bin/ffmpeg`).
- FFprobe: PASS (`/usr/bin/ffprobe`).
- Blender: BLOCKED (not installed).
- Runway / BFL / ElevenLabs / Kling / Higgsfield: BLOCKED (credentials absent; no connectivity tests made).
- ComfyUI: BLOCKED (base URL not configured; endpoint not tested).
- Real image/video/voice generation: NOT TESTED; provider calls are not implemented.
- User’s Claude Code host: NOT TESTED; this archive must be extracted and installed there by the user.

No paid provider calls were made and no subscription/credits were purchased.
