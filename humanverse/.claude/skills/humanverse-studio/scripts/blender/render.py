"""Render a list of frames of a scene .blend to <out>/NNNN.png (resumable: the caller passes only missing/corrupt frames).

Run:  <blender-python> render.py -- --blend scene.blend --out frames/ --frames 1-48,60 [--samples N] [--res WxH]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import bpy


def parse_frames(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def main():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--blend", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--frames", required=True)
    p.add_argument("--samples", type=int, default=0)
    p.add_argument("--res", default="")
    p.add_argument("--threads", type=int, default=0)
    A = p.parse_args(a)
    bpy.ops.wm.open_mainfile(filepath=A.blend)
    sc = bpy.context.scene
    if A.samples:
        sc.cycles.samples = A.samples
    if A.threads:
        sc.render.threads_mode = "FIXED"
        sc.render.threads = A.threads
    if A.res:
        sc.render.resolution_x, sc.render.resolution_y = map(int, A.res.lower().split("x"))
    os.makedirs(A.out, exist_ok=True)
    t0 = time.time()
    frames = parse_frames(A.frames)
    for f in frames:
        sc.frame_set(f)
        final = os.path.join(A.out, f"{f:04d}.png")
        tmp = os.path.join(A.out, f".{f:04d}.tmp.png")
        sc.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        os.replace(tmp, final)                       # a frame appears only when complete
        print(f"FRAME {f} {time.time() - t0:.1f}s", flush=True)
    print(f"RENDER_DONE {len(frames)} frames in {time.time() - t0:.1f}s ({(time.time() - t0) / max(1, len(frames)):.2f}s/frame)")


main()
