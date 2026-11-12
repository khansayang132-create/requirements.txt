"""Editing department: final assembly with FFmpeg, subtitles, preview and cover.

* ``mux``            picture + soundtrack → MP4 (H.264 / AAC 320 kbps, 48 kHz stereo, faststart),
                     two-pass loudness-normalised to the target (YouTube plays at about -14 LUFS),
                     true peak at or below -1.5 dBTP.
* ``write_srt``      a caption file from the script and the real shot timings.
* ``contact_sheet``  the preview a person (or the QA department) looks at before upload.
* ``cover_frame``    the frame offered as the Shorts cover.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image

from ..render.stage import Shot
from .animation import RenderError, ffmpeg_bin


AUDIO_RATE = 48000
AUDIO_BITRATE = "320k"


def _loudnorm_measure(cmd_in: list[str], af_prefix: str, loudness: float, true_peak: float) -> dict:
    af = f"{af_prefix}loudnorm=I={loudness}:TP={true_peak}:LRA=11:print_format=json"
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", *cmd_in, "-af", af, "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if proc.returncode != 0 or not m:
        raise RenderError(f"loudness measurement failed: {proc.stderr[-400:]}")
    return {k: float(v) if k != "normalization_type" else v for k, v in json.loads(m.group(0)).items()}


def measure_loudness(path: Path) -> dict:
    """Integrated loudness (LUFS) and true peak (dBTP) of a file's first audio stream, via ffmpeg ebur128."""
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                          capture_output=True, text=True)
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", proc.stderr)
    tp = re.findall(r"Peak:\s+(-?[\d.]+|-inf) dBFS", proc.stderr)
    return {"lufs": float(i[-1]) if i else None, "true_peak_dbtp": float(tp[-1]) if tp and tp[-1] != "-inf" else None}


def mux(video: Path, audio: Path, out: Path, loudness: float = -14.0, true_peak: float = -1.5) -> Path:
    """Picture + soundtrack -> MP4 with AAC 320 kbps, 48 kHz stereo, mastered to ``loudness`` LUFS integrated and
    a true peak at or below ``true_peak`` dBTP.

    Two-pass loudnorm: pass 1 measures the soundtrack, pass 2 applies the measured values in linear mode (one
    clean gain, no dynamic pumping; the soundtrack arrives already mastered close to target). The AAC encoder can
    overshoot peaks slightly, so pass 2 aims 0.5 dB under the ceiling, and the encoded result is measured: if it is
    off target by more than 0.3 LU or over the ceiling, one corrective gain is applied and the audio re-encoded."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tp_aim = true_peak - 0.5
    m = _loudnorm_measure(["-i", str(audio)], "", loudness, tp_aim)
    ln = (f"loudnorm=I={loudness}:TP={tp_aim}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")

    def encode(af: str, dst: Path) -> None:
        cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(AUDIO_RATE), "-ac", "2",
               "-movflags", "+faststart", "-shortest", str(dst)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not dst.exists():
            raise RenderError(f"mux failed: {proc.stderr[-400:]}")

    encode(f"{ln},aresample={AUDIO_RATE}", out)
    got = measure_loudness(out)
    if got["lufs"] is not None and got["true_peak_dbtp"] is not None:
        corr = loudness - got["lufs"]
        corr = min(corr, true_peak - 0.2 - got["true_peak_dbtp"])        # never push the peak over the ceiling
        if abs(loudness - got["lufs"]) > 0.3 or got["true_peak_dbtp"] > true_peak:
            tmp = out.with_name(out.stem + ".fix.mp4")
            encode(f"{ln},aresample={AUDIO_RATE},volume={corr:.2f}dB", tmp)
            tmp.replace(out)
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
