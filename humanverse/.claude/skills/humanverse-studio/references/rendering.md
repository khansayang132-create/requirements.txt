# Rendering

Measured on the build machine (4 CPU cores, no GPU, Blender 4.5.16 as the `bpy` module):

| Engine | Result |
|---|---|
| Cycles CPU | works; 1280×720, 8 samples + OpenImageDenoise: ~12 s/frame for a 5-character street shot |
| Eevee | needs OpenGL/EGL; only runs on Mesa llvmpipe (`EGL_PLATFORM=surfaceless`), 20 s for a single cube: slower than Cycles |
| Workbench | same EGL requirement; not useful without a GPU |

About 4 s of every frame is fixed cost (scene sync of deforming meshes, BVH, denoise), so more samples are cheap
and more resolution is not. 8 vs 14 samples were indistinguishable after denoising; 8 is the CPU profile.

## Profiles
- **LOW** (CPU only): 1280×720 render, 8 samples, denoised, delivered at 1920×1080 (Lanczos upscale, stated in the
  edit report).
- **STANDARD** (GPU ≥ 6 GB): 1920×1080, 32 samples.
- **CINEMATIC**: 1920×1080, 128 samples, depth of field everywhere, motion blur.
Never promise a render time before `hv render --limit 3` has measured one.

## Resumable
Each frame is written to a temp file and renamed only when complete. `hv render` checks every PNG's chunk CRCs and
renders only missing or corrupt frames, in chunks, re-checking after each chunk. Several scenes can render in
parallel with `--threads`.
