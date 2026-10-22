"""Deterministic technical QA for a finished video.

These checks prove the file is technically sound. They do not prove the video is
creatively good; that is reported separately and never folded into this score.
"""
from __future__ import annotations

import re
from pathlib import Path

from .media import MediaError, ffprobe, run_ffmpeg
from .models import Storyboard
from .subtitles import validate_srt


def _check(name: str, passed: bool, detail: str) -> dict:
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def _fps(stream: dict) -> float:
    num, den = stream.get("avg_frame_rate", "0/1").split("/")
    return float(num) / float(den) if float(den) else 0.0


def black_intervals(video: Path) -> list[tuple[float, float]]:
    log = run_ffmpeg(["-i", str(video), "-vf", "blackdetect=d=0.5:pix_th=0.06", "-an", "-f", "null", "-"])
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]


def silence_intervals(video: Path, min_seconds: float = 2.0) -> list[tuple[float, float]]:
    log = run_ffmpeg(["-i", str(video), "-af", f"silencedetect=n=-45dB:d={min_seconds}", "-vn", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    return list(zip(starts, ends))


def loudness(video: Path) -> dict:
    log = run_ffmpeg(["-i", str(video), "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"])
    summary = log[log.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return {"integrated_lufs": float(i.group(1)) if i else None, "true_peak_dbfs": float(tp.group(1)) if tp else None}


def sample_frames(video: Path, board: Storyboard, out_dir: Path) -> list[str]:
    """One frame from the middle of each scene, for human or vision-model review."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for s in board.scenes:
        p = out_dir / f"{s.scene_id}_mid.png"
        run_ffmpeg(["-ss", f"{s.start_time + s.duration / 2:.3f}", "-i", str(video), "-frames:v", "1", str(p)])
        paths.append(str(p))
    return paths


def technical_qa(video: Path, board: Storyboard, srt_text: str, target_seconds: float, tolerance: float,
                 expected_clips: int, frames_dir: Path) -> dict:
    checks = []
    exists = video.exists() and video.stat().st_size > 0
    checks.append(_check("file_exists_nonzero", exists, f"{video.stat().st_size if video.exists() else 0} bytes"))
    if not exists:
        return {"checks": checks, "technical_score": 0.0, "passed": False}
    try:
        info = ffprobe(video)
    except MediaError as e:
        checks.append(_check("ffprobe_readable", False, str(e)))
        return {"checks": checks, "technical_score": 0.0, "passed": False}
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    duration = float(info["format"]["duration"])
    checks.append(_check("ffprobe_readable", True, info["format"]["format_name"]))
    checks.append(_check("has_video_stream", v is not None, v["codec_name"] if v else "missing"))
    checks.append(_check("has_audio_stream", a is not None, a["codec_name"] if a else "missing"))
    if v:
        checks.append(_check("resolution", (v["width"], v["height"]) == (board.width, board.height),
                             f"{v['width']}x{v['height']} (expected {board.width}x{board.height})"))
        checks.append(_check("frame_rate", abs(_fps(v) - board.fps) < 0.01, f"{_fps(v):.3f} fps"))
        checks.append(_check("pixel_format_compatible", v.get("pix_fmt") == "yuv420p", v.get("pix_fmt", "?")))
        checks.append(_check("codec_h264", v["codec_name"] == "h264", v["codec_name"]))
    checks.append(_check("duration_matches_storyboard", abs(duration - board.total_seconds) <= 0.25,
                         f"{duration:.2f}s vs storyboard {board.total_seconds:.2f}s"))
    checks.append(_check("duration_within_target", abs(duration - target_seconds) <= tolerance,
                         f"{duration:.2f}s vs target {target_seconds:.0f}±{tolerance:.0f}s"))
    # Ignore only black that lies entirely inside the opening fade-in or the closing fade-out.
    blacks = [b for b in black_intervals(video) if not (b[1] <= 0.6 or b[0] >= duration - 0.7)]
    checks.append(_check("no_unexpected_black", not blacks, f"{len(blacks)} interval(s) ≥0.5s outside fades: {blacks}"))
    if a is not None:
        silences = [s for s in silence_intervals(video) if s[1] - s[0] >= 2.0]
        checks.append(_check("no_long_silence", not silences, f"silences ≥2s: {silences}"))
        loud = loudness(video)
        lufs, tp = loud["integrated_lufs"], loud["true_peak_dbfs"]
        checks.append(_check("loudness_target", lufs is not None and abs(lufs - (-14)) <= 2.0,
                             f"{lufs} LUFS (target -14±2)"))
        checks.append(_check("no_clipping", tp is not None and tp <= -0.5, f"true peak {tp} dBFS (must be ≤ -0.5)"))
    else:
        loud = {"integrated_lufs": None, "true_peak_dbfs": None}
        for name in ("no_long_silence", "loudness_target", "no_clipping"):
            checks.append(_check(name, False, "no audio stream to analyse"))
    srt_problems = validate_srt(srt_text)
    checks.append(_check("subtitle_syntax", not srt_problems, "; ".join(srt_problems) or "valid SRT"))
    checks.append(_check("all_scenes_assembled", expected_clips == len(board.scenes),
                         f"{expected_clips} clips for {len(board.scenes)} scenes"))
    frames = sample_frames(video, board, frames_dir)
    passed = sum(c["status"] == "PASS" for c in checks)
    return {"checks": checks, "technical_score": round(passed / len(checks), 3),
            "passed": passed == len(checks), "duration": duration, "loudness": loud,
            "sampled_frames": frames,
            "creative_review": {"status": "NOT RUN",
                                "detail": "sampled frames saved for human or vision-model review; "
                                          "technical checks do not measure creative quality"}}
