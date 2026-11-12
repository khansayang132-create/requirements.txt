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
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

from ..render import three_backend
from ..render.stage import Renderer, Shot

DISSOLVE_FRAMES = 7


class RenderError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RenderError("ffmpeg not found on PATH (apt install ffmpeg / pkg install ffmpeg)")
    return path


def resolve_backend(backend: str) -> tuple[str, str]:
    """(backend actually used, why). "three" raises RenderError when the 3D renderer cannot run."""
    if backend == "flat":
        return "flat", "requested flat"
    if backend not in ("three", "auto"):
        raise RenderError(f"unknown backend {backend!r} (flat | three | auto)")
    ok, why = three_backend.available()
    if ok:
        return "three", f"3D renderer available: {why}"
    if backend == "three":
        raise RenderError(f"3D backend requested but unavailable: {why}")
    return "flat", f"3D renderer unavailable, fell back to flat: {why}"


def _render_segment(job: tuple) -> dict:
    idx, shots, universe, width, height, fps, crf, preset, out_path, starts, backend = job
    try:
        return _render_segment_inner(idx, shots, universe, width, height, fps, crf, preset, out_path, starts, backend)
    except three_backend.ThreeError as e:
        raise RenderError(f"3D renderer failed on shot {idx}: {e}") from None


def _render_segment_inner(idx, shots, universe, width, height, fps, crf, preset, out_path, starts, backend) -> dict:
    shot: Shot = shots[idx]
    prev: Shot | None = shots[idx - 1] if idx > 0 else None
    r = Renderer(universe, width, height, fps)
    if backend == "three":
        r.three = three_backend.session_for(universe, width, height)
    n = max(1, round(shot.duration * fps))
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
           "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-threads", "1", "-video_track_timescale", "12288", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    dissolve = DISSOLVE_FRAMES if (prev is not None and prev.env != shot.env) else 0
    prev_last = r.frame(prev, max(0.0, prev.duration - 1 / fps), starts[idx] - 1 / fps) if dissolve else None
    three = r.three is not None and bool(shot.actors)
    try:
        if three:                      # pipelined: the browser renders frame f+1 while we composite frame f
            r.submit_layer(shot, 0.0, starts[idx])
        for f in range(n):
            t = f / fps
            layer = None
            if three:
                layer = r.three.collect()
                if f + 1 < n:
                    r.submit_layer(shot, (f + 1) / fps, starts[idx] + (f + 1) / fps)
            img = r.frame(shot, t, starts[idx] + t, layer=layer)
            if f < dissolve:
                img = Image.blend(prev_last, img, (f + 1) / (dissolve + 1))
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        raise RenderError(f"ffmpeg failed on shot {idx}: {err[-400:]}")
    return {"index": idx, "frames": n, "path": str(out_path)}


def render_video(shots: list[Shot], universe: dict, out_path: Path, work_dir: Path, *, width: int = 1080, height: int = 1920,
                 fps: int = 24, crf: int = 19, preset: str = "medium", workers: int | None = None, backend: str = "auto") -> dict:
    """Render all shots and join them. Returns {"frames","seconds","segments","render_seconds","workers","backend","backend_reason"}.

    ``backend``: "flat" = the built-in 2D renderer; "three" = real-3D characters (Three.js in headless Chromium,
    see wonderland/render/three_backend.py) or RenderError with the reason; "auto" = three when it is available
    on this machine, else flat. Each worker process keeps one browser for all its shots.
    """
    t0 = time.time()
    used, reason = resolve_backend(backend)
    work_dir.mkdir(parents=True, exist_ok=True)
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += s.duration
    jobs = [(i, shots, universe, width, height, fps, crf, preset, work_dir / f"seg_{i:03d}.mp4", starts, used) for i in range(len(shots))]
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 2)))
    # longest shots first so the last worker is not left with a long tail
    order = sorted(range(len(jobs)), key=lambda i: -shots[i].duration)
    if workers == 1:
        try:
            results = [_render_segment(jobs[i]) for i in order]
        finally:
            three_backend.close_all()
    else:
        ctx = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context("spawn")
        try:
            with ProcessPoolExecutor(workers, mp_context=ctx) as pool:
                results = list(pool.map(_render_segment, [jobs[i] for i in order]))
        except BrokenProcessPool as e:     # a worker died (e.g. killed browser host): fail, never hang
            raise RenderError(f"a render worker died: {e}") from None
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
            "render_seconds": round(time.time() - t0, 1), "width": width, "height": height, "fps": fps, "backend": used,
            "backend_reason": reason}


SHEET_VARIANTS = [dict(), dict(mouth=0.7, arm_r=140), dict(mood="wow", arm_l=110, arm_r=110), dict(blink=1.0, head_tilt=-6), dict(mood="sleepy"),
                  dict(mood="sad", head_tilt=6)]
SHEET_LABELS = ["happy", "talking + wave", "wow", "blink + tilt", "sleepy", "sad"]


def _paste_layer_at(img, layer, dx: float, dy: float, k: float) -> None:
    """Paste a premultiplied 3D layer onto ``img`` shifted by (dx, dy) design px (sheet scale k)."""
    from PIL import ImageChops

    if layer.rgba is None:
        return
    x0, y0, w, h = layer.box
    im = Image.frombuffer("RGBa", (w, h), layer.rgba.tobytes(), "raw", "RGBa", 0, 1)
    if abs(k - 1) > 1e-6:
        im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.BILINEAR)
    X, Y = round((x0 + dx) * k), round((y0 + dy) * k)
    r, g, b, a = im.split()
    region = img.crop((X, Y, X + im.width, Y + im.height))
    inv = ImageChops.invert(a)
    img.paste(ImageChops.add(ImageChops.multiply(region, Image.merge("RGB", (inv, inv, inv))), Image.merge("RGB", (r, g, b))), (X, Y))


def character_sheet(universe: dict, out_path: Path, width: int = 1080, backend: str = "flat") -> Path:
    """Reference sheet: every character in several poses and moods (the 'character references' stage).
    ``backend="three"`` draws the real-3D models (RenderError if the 3D renderer is unavailable)."""
    from ..render.canvas import Canvas, draw_text, vertical_gradient
    from ..render.characters import Pose, draw_character

    chars = universe["characters"]
    rows = len(chars)
    H = 420 * rows + 140
    ss = 2 * width / 1080
    k = width / 1080
    if backend == "three":
        used, why = resolve_backend("three")
        img = vertical_gradient(width, round(H * k), [(0, "#FFF6E3"), (1, "#FDE9CF")])
        try:
            with three_backend.Session(chars, 1080, 1920) as s:
                s.set_lights("sheet", three_backend.light_preset("meadow"))
                for r, spec in enumerate(chars):
                    y = 140 + 420 * r + 380
                    for i, v in enumerate(SHEET_VARIANTS):
                        p = Pose(x=540, y=1340, scale=0.46, **v)
                        layer = s.render([three_backend.pose_record(spec["id"], p, 1.0, 24.0)])
                        _paste_layer_at(img, layer, 110 + i * 172 - 540, y - 1340, k)
        except three_backend.ThreeError as e:
            raise RenderError(f"3D character sheet failed: {e}") from None
        title = f"{universe['brand']['universe']} — 3D character reference sheet"
    else:
        c = Canvas(1080, H, ss, base=vertical_gradient(round(1080 * ss), round(H * ss), [(0, "#FFF6E3"), (1, "#FDE9CF")]))
        for r, spec in enumerate(chars):
            y = 140 + 420 * r + 380
            for i, v in enumerate(SHEET_VARIANTS):
                p = Pose(x=110 + i * 172, y=y, scale=0.46, **v)
                draw_character(c, spec, p, shadow_color=(238, 214, 180))
        img = c.finish()
        title = f"{universe['brand']['universe']} — character reference sheet"
    draw_text(img, title, width / 2, 60 * k, round(44 * k), (59, 51, 85), weight=700)
    for r, spec in enumerate(chars):
        draw_text(img, f"{spec['name']} the {spec['species']}  ·  {spec['clothing']['note']}", 30 * k, (150 + 420 * r) * k, round(30 * k),
                  (59, 51, 85), weight=600, anchor="lm")
        if backend == "three":
            for i, lab in enumerate(SHEET_LABELS):
                draw_text(img, lab, (110 + i * 172) * k, (140 + 420 * r + 404) * k, round(20 * k), (120, 110, 140), weight=500)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


TURN_ANGLES = [("front", 0.0, 0.0), ("3/4 left", -45.0, 0.0), ("left", -90.0, 0.0), ("back", 180.0, 0.0), ("right", 90.0, 0.0),
               ("3/4 right", 45.0, 0.0), ("top-down", 0.0, 70.0)]


def character_turnaround(universe: dict, char_id: str, out_path: Path, width: int = 1680) -> Path:
    """One character from 7 angles (front, 3/4 left, left, back, right, 3/4 right, top-down) on one sheet,
    rendered with the 3D backend (the 'approved turnaround' identity reference)."""
    from ..render.canvas import draw_text, vertical_gradient
    from ..render.characters import Pose

    spec = next((c for c in universe["characters"] if c["id"] == char_id), None)
    if spec is None:
        raise ValueError(f"unknown character {char_id!r}")
    resolve_backend("three")
    cell, H = 240, 620
    k = width / (cell * 7)
    img = vertical_gradient(width, round(H * k), [(0, "#FFF6E3"), (1, "#FDE9CF")])
    try:
        with three_backend.Session([spec], 1080, 1920) as s:
            s.set_lights("sheet", three_backend.light_preset("meadow"))
            for i, (name, yaw, pitch) in enumerate(TURN_ANGLES):
                p = Pose(x=540, y=1340, scale=0.62)
                rec = three_backend.pose_record(spec["id"], p, -1.0 if yaw < 0 else 1.0, yaw)
                rec["pitch"] = pitch
                if pitch:
                    rec["lift"] = 120.0
                layer = s.render([rec], shadow=not pitch)
                _paste_layer_at(img, layer, cell * i + cell / 2 - 540, 520 - 1340, k)
                draw_text(img, name, (cell * i + cell / 2) * k, 566 * k, round(26 * k), (59, 51, 85), weight=600)
    except three_backend.ThreeError as e:
        raise RenderError(f"3D turnaround failed: {e}") from None
    draw_text(img, f"{spec['name']} the {spec['species']} — turnaround", width / 2, 44 * k, round(36 * k), (59, 51, 85), weight=700)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
