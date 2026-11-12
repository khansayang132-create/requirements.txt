"""FFmpeg calls with explicit argument lists (no shell, no string interpolation into a shell)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..errors import DHFError


def binary(name: str = "ffmpeg") -> str:
    path = shutil.which(name)
    if not path:
        raise DHFError(f"{name} not found on PATH")
    return path


def run(args: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
    proc = subprocess.run([binary(), "-hide_banner", "-loglevel", "error", "-y", *args], check=False, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise DHFError(f"ffmpeg failed: {proc.stderr[-500:]}")
    return proc


def normalize(src: Path, out: Path, width: int, height: int, fps: int = 30) -> Path:
    """Fit any provider clip into the job frame (letterbox, never stretch) with AAC 48 kHz stereo."""
    vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x202024,fps={fps},format=yuv420p"
    run(["-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         "-movflags", "+faststart", str(out)])
    return out


def concat(clips: list[Path], out: Path, work: Path) -> Path:
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)])
    return out


def finish(video: Path, out: Path, subtitles: Path | None, music: Path | None, music_db: float = -24.0, grade: bool = True) -> Path:
    """Burn captions, add an optional music bed under the voice, light grade, loudness -14 LUFS."""
    filters = []
    if grade:
        filters.append("eq=contrast=1.04:saturation=1.05")
    if subtitles:
        style = "FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=2,MarginV=60"
        filters.append(f"subtitles={subtitles.as_posix()}:force_style='{style}'")
    args = ["-i", str(video)]
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]
        af = f"[1:a]volume={music_db}dB[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        args += ["-filter_complex", af, "-map", "0:v", "-map", "[a]"]
    else:
        args += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-movflags", "+faststart", "-shortest", str(out)]
    run(args)
    return out
