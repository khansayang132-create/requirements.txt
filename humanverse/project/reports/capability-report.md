# Capability report

| Capability | Status |
|---|---|
| Modeling / rigging / animation (Blender Python API) | PASS |
| Rendering | PASS: Cycles CPU |
| Eevee | NOT TESTED here: needs OpenGL/EGL; without a GPU it only runs on Mesa llvmpipe and is slower than Cycles CPU |
| Video assembly (FFmpeg) | PASS |
| Speech (eSpeak NG, phoneme timing) | PASS: libespeak-ng via espeakng-loader (GPL-3.0 engine; output unrestricted) |
| Speech (Piper, neural) | BLOCKED: piper not on PATH; voice models download from huggingface.co |
| MakeHuman / MPFB base meshes | NOT USED: not installed; characters are procedural (hvchar.py) |
| ComfyUI | NOT USED: no local server configured; nothing in this pipeline needs it |
| Quality profile chosen | LOW (CPU only: Cycles, 12-16 samples + denoiser) |
