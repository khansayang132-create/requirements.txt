"""Editing department: final assembly with FFmpeg, subtitles, preview and cover.

* ``mux``            picture + soundtrack → MP4 (H.264 / AAC, 44.1 kHz stereo, faststart),
                     loudness-normalised to the target (YouTube plays at about -14 LUFS).
* ``write_srt``      a caption file from the script and the real shot timings.
* ``contact_sheet``  the preview a person (or the QA department) looks at before upload.
* ``cover_frame``    the frame offered as the Shorts cover.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image

from ..render.stage import Shot
from .animation import RenderError, ffmpeg_bin


def mux(video: Path, audio: Path, out: Path, loudness: float = -14.0, true_peak: float = -1.5) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
           "-af", f"loudnorm=I={loudness}:TP={true_peak}:LRA=11", "-movflags", "+faststart", "-shortest", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise RenderError(f"mux failed: {proc.stderr[-400:]}")
    return out


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(shots: list[Shot], out: Path) -> Path:
    lines, t = [], 0.0
    n = 0
    for s in shots:
        if s.caption.strip() and s.voice:
            n += 1
            a = t + s.voice.start
            b = min(t + s.duration, a + s.voice.duration + 0.25)
            lines.append(f"{n}\n{_ts(a)} --> {_ts(b)}\n{s.caption.strip()}\n")
        t += s.duration
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def grab_frame(video: Path, t: float, out: Path, width: int | None = None) -> Path:
    vf = ["-vf", f"scale={width}:-2"] if width else []
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1", *vf, str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise RenderError(f"frame grab failed at {t:.2f}s: {proc.stderr[-300:]}")
    return out


def contact_sheet(video: Path, shots: list[Shot], out: Path, columns: int = 4, thumb_w: int = 270) -> dict:
    """One frame from the middle of (up to 12) shots, tiled. Returns {"path","times"}."""
    times, t = [], 0.0
    for s in shots:
        times.append(t + min(s.duration * 0.6, s.duration - 0.05))
        t += s.duration
    if len(times) > 12:
        step = len(times) / 12
        times = [times[int(i * step)] for i in range(12)]
    tmp = out.parent / "_sheet"
    tmp.mkdir(parents=True, exist_ok=True)
    thumbs = []
    for i, tt in enumerate(times):
        p = grab_frame(video, tt, tmp / f"f{i:02d}.png", thumb_w)
        thumbs.append(Image.open(p).convert("RGB"))
    th = thumbs[0].height
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * th), (30, 26, 44))
    for i, im in enumerate(thumbs):
        sheet.paste(im, ((i % columns) * thumb_w, (i // columns) * th))
    sheet.save(out)
    for p in tmp.glob("*.png"):
        p.unlink()
    tmp.rmdir()
    return {"path": str(out), "times": [round(x, 2) for x in times]}


def cover_frame(video: Path, shots: list[Shot], out: Path) -> dict:
    """Cover = the title shot once the title has popped in (honest: it is a real frame of the video)."""
    t = min(1.2, shots[0].duration - 0.1) if shots else 0.5
    grab_frame(video, t, out)
    return {"path": str(out), "time": round(t, 2)}
