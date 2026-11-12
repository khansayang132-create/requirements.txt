"""ffprobe stream/duration/dimension check plus a full FFmpeg decode test (a file that probes but does not decode is a FAIL)."""

import json
import shutil
import subprocess
from pathlib import Path


def probe_video(path: str) -> dict:
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        return {"status": "BLOCKED", "reason": "ffmpeg/ffprobe not installed"}
    p = Path(path)
    if not p.is_file():
        return {"status": "FAIL", "reason": f"File not found: {path}"}
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)], capture_output=True, text=True, check=False)
    if r.returncode:
        return {"status": "FAIL", "stderr": r.stderr}
    data = json.loads(r.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "null", "-"], capture_output=True, text=True, check=False)
    decode_ok = dec.returncode == 0 and not dec.stderr.strip()
    duration = float((data.get("format") or {}).get("duration") or 0)
    summary = {"duration_seconds": round(duration, 2), "width": video and video.get("width"), "height": video and video.get("height"),
               "video_codec": video and video.get("codec_name"), "audio_codec": audio and audio.get("codec_name"),
               "decode_ok": decode_ok, "decode_errors": dec.stderr.strip()[:500]}
    ok = bool(video) and decode_ok and duration > 0
    return {"status": "PASS" if ok else "FAIL", "summary": summary, "has_audio": bool(audio), "video": video, "audio": audio,
            "format": data.get("format")}
