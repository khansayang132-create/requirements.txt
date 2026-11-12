"""Quality control: automated technical checks on the finished file.

A video is uploaded only if every check passes. The checks measure the actual MP4
with ffprobe/ffmpeg — nothing is assumed from how it was made:

  container/codecs   MP4, H.264 (yuv420p), AAC stereo 48 kHz at a high bit rate, moov atom first (faststart)
  picture            exact resolution, 9:16, frame rate, no black frames, no blank
                     (single-colour) frames, no long freezes, first frame is a real picture
  sound              audible throughout (no long silence), integrated loudness within 1 LU of the
                     target (-14 LUFS), true peak at or below -1.5 dBTP (BS.1770, ffmpeg ebur128)
  timing             duration inside the Shorts window; audio and video the same length

"Looks good / is a nice story" is NOT decided here: content review is the compliance
department's job and creative review is the owner's (review mode).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from .animation import ffmpeg_bin


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(video: Path) -> dict:
    ffprobe = ffmpeg_bin().replace("ffmpeg", "ffprobe")
    p = _run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)])
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[-300:]}")
    return json.loads(p.stdout)


def _fps(stream: dict) -> float:
    num, den = stream.get("avg_frame_rate", "0/1").split("/")
    return float(num) / float(den) if float(den) else 0.0


def moov_before_mdat(video: Path) -> bool:
    data = video.read_bytes()[: 4 * 1024 * 1024]
    a, b = data.find(b"moov"), data.find(b"mdat")
    return a != -1 and (b == -1 or a < b)


def detect(video: Path, vf: str | None, af: str | None) -> str:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(video)]
    if vf:
        cmd += ["-vf", vf]
    else:
        cmd += ["-vn"]
    if af:
        cmd += ["-af", af]
    else:
        cmd += ["-an"]
    cmd += ["-f", "null", "-"]
    return _run(cmd).stderr


def frame_stats(video: Path, times: list[float]) -> list[float]:
    """Standard deviation of pixel values of small sampled frames (0 = one flat colour)."""
    out = []
    for t in times:
        p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                            "-vf", "scale=90:160", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
        if len(p.stdout) < 90 * 160 * 3:
            out.append(0.0)
            continue
        arr = np.frombuffer(p.stdout[: 90 * 160 * 3], dtype=np.uint8)
        out.append(float(arr.std()))
    return out


def technical_qa(video: Path, *, width: int, height: int, fps: int, min_seconds: float, max_seconds: float,
                 loudness: float = -14.0, true_peak: float = -1.5, loudness_tolerance: float = 1.0) -> dict:
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    info = probe(video)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    fmt = info["format"]
    dur = float(fmt.get("duration", 0))
    check("container_mp4", "mp4" in fmt.get("format_name", ""), fmt.get("format_name", "?"))
    check("has_video_stream", v is not None, "found" if v else "missing")
    check("has_audio_stream", a is not None, "found" if a else "missing")
    metrics: dict = {"duration": round(dur, 3), "bytes": int(fmt.get("size", 0))}
    if v:
        check("video_codec_h264", v.get("codec_name") == "h264", v.get("codec_name", "?"))
        check("pixel_format_yuv420p", v.get("pix_fmt") == "yuv420p", v.get("pix_fmt", "?"))
        check("resolution", (v.get("width"), v.get("height")) == (width, height), f"{v.get('width')}x{v.get('height')} (want {width}x{height})")
        check("aspect_9_16", abs(v.get("width", 0) / max(1, v.get("height", 1)) - 9 / 16) < 0.002, f"{v.get('width')}:{v.get('height')}")
        f = _fps(v)
        check("frame_rate", abs(f - fps) < 0.05, f"{f:.3f} fps (want {fps})")
        metrics["fps"] = round(f, 3)
    if a:
        check("audio_codec_aac", a.get("codec_name") == "aac", a.get("codec_name", "?"))
        check("audio_48000_stereo", a.get("sample_rate") == "48000" and a.get("channels") == 2, f"{a.get('sample_rate')} Hz, {a.get('channels')} ch")
        br = int(a.get("bit_rate") or 0)
        metrics["audio_kbps"] = round(br / 1000)
        # requested 320 kbps; the native AAC encoder spends less on sparse, quiet material, so the floor is 192
        check("audio_bitrate_high", br >= 192000, f"{br / 1000:.0f} kbps (requested 320, floor 192)")
    check("duration_window", min_seconds <= dur <= max_seconds, f"{dur:.2f}s (want {min_seconds:g}-{max_seconds:g}s)")
    if v and a:
        dv, da = float(v.get("duration", dur)), float(a.get("duration", dur))
        check("audio_video_same_length", abs(dv - da) <= 0.15, f"video {dv:.2f}s, audio {da:.2f}s")
    check("faststart_moov_first", moov_before_mdat(video), "moov atom before mdat")

    if v:
        log = detect(video, "blackdetect=d=0.08:pix_th=0.10,freezedetect=n=0.002:d=3.0", None)
        blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)
        freezes = re.findall(r"freeze_duration: ([\d.]+)", log)
        check("no_black_frames", not blacks, "none" if not blacks else f"{len(blacks)} black interval(s): {blacks[:3]}")
        check("no_long_freeze", not freezes, "none" if not freezes else f"frozen for {freezes[:3]} s")
        n = 8
        times = [0.0] + [dur * (i + 0.5) / n for i in range(n)] + [max(0.0, dur - 0.2)]
        stds = frame_stats(video, times)
        metrics["frame_std_min"] = round(min(stds), 2)
        check("no_blank_frames", min(stds) > 12.0, f"lowest picture detail {min(stds):.1f} (flat colour = 0)")
        check("first_frame_is_picture", stds[0] > 12.0, f"detail {stds[0]:.1f}")
    if a:
        log = detect(video, None, "silencedetect=n=-42dB:d=2.5,ebur128=peak=true")
        silences = re.findall(r"silence_duration: ([\d.]+)", log)
        check("no_long_silence", not silences, "none" if not silences else f"silent for {silences[:3]} s")
        m = re.search(r"Integrated loudness:\s+I:\s+(-?[\d.]+) LUFS", log)
        pk = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+) dBFS", log)
        lufs = float(m.group(1)) if m else None
        peak = float(pk.group(1)) if pk else None
        metrics.update({"lufs": lufs, "true_peak_dbfs": peak})
        check("loudness_on_target", lufs is not None and abs(lufs - loudness) <= loudness_tolerance,
              f"{lufs} LUFS (target {loudness:g} ±{loudness_tolerance:g})")
        check("true_peak_ceiling", peak is not None and peak <= true_peak, f"true peak {peak} dBTP (ceiling {true_peak:g})")
    return {"ok": all(c["passed"] for c in checks), "checks": checks, "metrics": metrics,
            "failed": [c["name"] for c in checks if not c["passed"]], "scope": "technical only; content review is separate"}


def sync_report(shots, fps: int) -> dict:
    """Audio/picture sync evidence: every line starts inside its own shot and its mouth track is as long as its audio."""
    worst = 0.0
    problems = []
    for i, s in enumerate(shots):
        if not s.voice:
            continue
        end = s.voice.start + s.voice.duration
        if end > s.duration + 1 / fps:
            problems.append(f"shot {i}: line runs {end - s.duration:.2f}s past the shot")
        drift = abs(len(s.voice.envelope) / fps - s.voice.duration)
        worst = max(worst, drift)
        if drift > 2 / fps + 0.02:
            problems.append(f"shot {i}: lip-sync track differs from audio by {drift:.3f}s")
    return {"ok": not problems, "worst_drift_seconds": round(worst, 4), "problems": problems,
            "method": "mouth openness is computed from each recorded line and indexed by video frame"}


def image_ok(path: Path, min_std: float = 12.0) -> bool:
    arr = np.asarray(Image.open(path).convert("RGB").resize((90, 160)))
    return float(arr.std()) > min_std
