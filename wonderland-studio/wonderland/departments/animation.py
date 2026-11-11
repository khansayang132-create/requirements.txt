"""Animation department: shots → silent H.264 video.

Each shot is rendered by its own worker process straight into an ffmpeg encoder
(one segment per shot), then the segments are joined without re-encoding. A frame is a
pure function of (shot, time), so workers need no shared state, a crashed render can
simply be re-run, and the same storyboard always produces the same pictures.

Scene changes get a short cross-dissolve; there are no fades to black, so the video
never contains a blank frame (and the first frame is a real picture for the Shorts feed).
"""

from __future__ import annotations

import multiprocessing as mp
import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

from ..render.stage import Renderer, Shot

DISSOLVE_FRAMES = 7


class RenderError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RenderError("ffmpeg not found on PATH (apt install ffmpeg / pkg install ffmpeg)")
    return path


def _render_segment(job: tuple) -> dict:
    idx, shots, universe, width, height, fps, crf, preset, out_path, starts = job
    shot: Shot = shots[idx]
    prev: Shot | None = shots[idx - 1] if idx > 0 else None
    r = Renderer(universe, width, height, fps)
    n = max(1, round(shot.duration * fps))
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
           "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-threads", "1", "-video_track_timescale", "12288", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    dissolve = DISSOLVE_FRAMES if (prev is not None and prev.env != shot.env) else 0
    prev_last = r.frame(prev, max(0.0, prev.duration - 1 / fps), starts[idx] - 1 / fps) if dissolve else None
    try:
        for f in range(n):
            t = f / fps
            img = r.frame(shot, t, starts[idx] + t)
            if f < dissolve:
                img = Image.blend(prev_last, img, (f + 1) / (dissolve + 1))
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RenderError(f"ffmpeg failed on shot {idx}: {err[-400:]}")
    return {"index": idx, "frames": n, "path": str(out_path)}


def render_video(shots: list[Shot], universe: dict, out_path: Path, work_dir: Path, *, width: int = 1080, height: int = 1920,
                 fps: int = 24, crf: int = 19, preset: str = "medium", workers: int | None = None, backend: str = "auto") -> dict:
    """Render all shots and join them. Returns {"frames","seconds","segments","render_seconds","workers","backend"}.

    ``backend``: "flat" = the built-in 2D renderer; "three" = real-3D characters; "auto" = three when it is
    available on this machine, else flat. (Only "flat" exists until the 3D backend lands.)
    """
    t0 = time.time()
    work_dir.mkdir(parents=True, exist_ok=True)
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += s.duration
    jobs = [(i, shots, universe, width, height, fps, crf, preset, work_dir / f"seg_{i:03d}.mp4", starts) for i in range(len(shots))]
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 2)))
    if workers == 1:
        results = [_render_segment(j) for j in jobs]
    else:
        ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context("spawn")
        with ctx.Pool(workers) as pool:
            results = pool.map(_render_segment, jobs, chunksize=1)
    listing = work_dir / "segments.txt"
    listing.write_text("".join(f"file '{Path(r['path']).resolve()}'\n" for r in sorted(results, key=lambda r: r["index"])))
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        raise RenderError(f"joining segments failed: {proc.stderr[-400:]}")
    for r in results:
        Path(r["path"]).unlink(missing_ok=True)
    listing.unlink(missing_ok=True)
    frames = sum(r["frames"] for r in results)
    return {"frames": frames, "seconds": round(frames / fps, 3), "segments": len(results), "workers": workers,
            "render_seconds": round(time.time() - t0, 1), "width": width, "height": height, "fps": fps, "backend": "flat"}


def character_sheet(universe: dict, out_path: Path, width: int = 1080) -> Path:
    """Reference sheet: every character in several poses and moods (the 'character references' stage)."""
    from ..render.canvas import Canvas, draw_text, vertical_gradient
    from ..render.characters import Pose, draw_character

    chars = universe["characters"]
    rows = len(chars)
    H = 420 * rows + 140
    ss = 2 * width / 1080
    c = Canvas(1080, H, ss, base=vertical_gradient(round(1080 * ss), round(H * ss), [(0, "#FFF6E3"), (1, "#FDE9CF")]))
    variants = [dict(), dict(mouth=0.7, arm_r=140), dict(mood="wow", arm_l=110, arm_r=110), dict(blink=1.0, head_tilt=-6), dict(mood="sleepy"),
                dict(mood="sad", head_tilt=6)]
    for r, spec in enumerate(chars):
        y = 140 + 420 * r + 380
        for i, v in enumerate(variants):
            p = Pose(x=110 + i * 172, y=y, scale=0.46, **v)
            draw_character(c, spec, p, shadow_color=(238, 214, 180))
    img = c.finish()
    k = width / 1080
    draw_text(img, f"{universe['brand']['universe']} — character reference sheet", width / 2, 60 * k, round(44 * k), (59, 51, 85), weight=700)
    for r, spec in enumerate(chars):
        draw_text(img, f"{spec['name']} the {spec['species']}  ·  {spec['clothing']['note']}", 30 * k, (150 + 420 * r) * k, round(30 * k),
                  (59, 51, 85), weight=600, anchor="lm")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
