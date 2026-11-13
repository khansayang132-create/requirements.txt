"""Evidence checks for media: PNG integrity, FFprobe, WAV, loudness, black/frozen picture detection."""

from __future__ import annotations

import json
import re
import struct
import subprocess
import wave
import zlib
from pathlib import Path

import numpy as np

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_ok(path: Path) -> tuple[bool, str]:
    """Signature plus every chunk CRC; a frame half-written by a crashed render fails here."""
    try:
        with open(path, "rb") as f:
            if f.read(8) != PNG_SIG:
                return False, "bad_signature"
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return False, "truncated"
                n, kind = struct.unpack(">I4s", hdr)
                data, crc = f.read(n), f.read(4)
                if len(data) < n or len(crc) < 4:
                    return False, "truncated"
                if struct.unpack(">I", crc)[0] != zlib.crc32(kind + data) & 0xFFFFFFFF:
                    return False, "crc_mismatch"
                if kind == b"IEND":
                    return True, "ok"
    except FileNotFoundError:
        return False, "missing"


def scan_frames(folder: Path, first: int, last: int) -> dict:
    missing, corrupt = [], []
    for i in range(first, last + 1):
        p = Path(folder) / f"{i:04d}.png"
        ok, why = png_ok(p)
        if not ok:
            (missing if why == "missing" else corrupt).append(i)
    return {"missing": missing, "corrupt": corrupt, "valid": (last - first + 1) - len(missing) - len(corrupt)}


def ffprobe(path: Path) -> dict | None:
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True, text=True, check=False)
    if r.returncode:
        return None
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    s = next((s for s in d["streams"] if s["codec_type"] == "subtitle"), None)
    out = {"duration": float(d["format"].get("duration", 0)), "size": int(d["format"].get("size", 0))}
    if v:
        num, den = v["r_frame_rate"].split("/")
        out.update(vcodec=v["codec_name"], width=v["width"], height=v["height"], fps=round(float(num) / float(den), 3),
                   pix_fmt=v.get("pix_fmt"), v_duration=float(v.get("duration", out["duration"])))
    if a:
        out.update(acodec=a["codec_name"], sample_rate=int(a["sample_rate"]), channels=a["channels"],
                   a_duration=float(a.get("duration", out["duration"])))
    if s:
        out["subtitles"] = s["codec_name"]
    return out


def decode_ok(path: Path) -> tuple[bool, str]:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True, check=False)
    return r.returncode == 0 and not r.stderr.strip(), r.stderr.strip()[:300]


def black_and_freeze(path: Path) -> dict:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.06,freezedetect=n=0.002:d=2.5",
                        "-an", "-f", "null", "-"], capture_output=True, text=True, check=False)
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", r.stderr)
    freezes = re.findall(r"freeze_start: ([\d.]+)", r.stderr)
    return {"black": [(float(a), float(b)) for a, b in blacks], "freeze_starts": [float(x) for x in freezes]}


def loudness(path: Path, target_i=-16.0, tp=-1.5, lra=11.0) -> dict | None:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True, check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        return None
    d = json.loads(m.group(0))
    return {k: float(d[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


def loudnorm_two_pass(src: Path, dst: Path, target_i=-16.0, tp=-1.5, lra=11.0) -> dict:
    m = loudness(src, target_i, tp, lra)
    if not m:
        raise RuntimeError("loudness measurement failed")
    af = (f"loudnorm=I={target_i}:TP={tp}:LRA={lra}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", "48000", "-ac", "2", str(dst)], check=True)
    return {"measured": m, "after": loudness(dst, target_i, tp, lra)}


def wav_stats(path: Path) -> dict:
    with wave.open(str(path), "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    x = x.reshape(-1, ch).mean(axis=1) if ch > 1 else x
    win = max(1, sr // 10)
    frames = x[: len(x) // win * win].reshape(-1, win)
    rms = np.sqrt((frames ** 2).mean(axis=1)) if len(frames) else np.zeros(1)
    silent = rms < 10 ** (-50 / 20)
    longest, run = 0, 0
    for s in silent:
        run = run + 1 if s else 0
        longest = max(longest, run)
    return {"sr": sr, "channels": ch, "duration": round(n / sr, 3), "rms": round(float(np.sqrt((x ** 2).mean())), 5),
            "peak": round(float(np.abs(x).max()), 4), "clipped_samples": int((np.abs(x) >= 0.999).sum()), "longest_silence_s": round(longest * 0.1, 2)}
