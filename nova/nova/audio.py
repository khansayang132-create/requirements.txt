"""Audio I/O: decode anything ffmpeg understands, resample, write WAV/MP3, verify outputs."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SUPPORTED_RATES = (16000, 22050, 24000, 44100, 48000)


class AudioError(RuntimeError):
    pass


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float64)


def to_mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def load_audio(path: str | Path, sr: int | None = None) -> tuple[np.ndarray, int]:
    """Read any file ffmpeg can decode (wav, mp3, m4a, ogg, webm from the browser recorder)."""
    path = Path(path)
    try:
        x, rate = sf.read(str(path), dtype="float64", always_2d=False)
    except Exception:
        if not shutil.which("ffmpeg"):
            raise AudioError("ffmpeg is required to decode this format")
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "decoded.wav"
            proc = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-ac", "1", str(wav)],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0 or not wav.exists():
                raise AudioError(f"could not decode audio: {proc.stderr.strip()[:300]}")
            x, rate = sf.read(str(wav), dtype="float64", always_2d=False)
    x = to_mono(np.asarray(x, dtype=np.float64))
    if sr and rate != sr:
        x, rate = resample(x, rate, sr), sr
    return x, int(rate)


def write_wav(path: str | Path, x: np.ndarray, sr: int, subtype: str = "PCM_16") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.clip(x, -1.0, 1.0), sr, subtype=subtype)
    return path


def write_mp3(path: str | Path, x: np.ndarray, sr: int, bitrate: str = "192k") -> Path:
    path = Path(path)
    if not shutil.which("ffmpeg"):
        raise AudioError("ffmpeg is required for MP3 export")
    with tempfile.TemporaryDirectory() as td:
        wav = write_wav(Path(td) / "in.wav", x, sr, subtype="PCM_24")
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame",
             "-b:a", bitrate, str(path)],
            capture_output=True, text=True, timeout=300,
        )
    if proc.returncode != 0:
        raise AudioError(f"MP3 encode failed: {proc.stderr.strip()[:300]}")
    return path


def export(path: str | Path, x: np.ndarray, sr: int, fmt: str) -> Path:
    fmt = fmt.lower()
    if fmt == "wav":
        return write_wav(path, x, sr)
    if fmt == "mp3":
        return write_mp3(path, x, sr)
    raise AudioError(f"unsupported format {fmt!r} (use wav or mp3)")


def probe(path: str | Path) -> dict:
    """Independent check of an output file with ffprobe: codec, rate, channels, duration."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,sample_rate,channels:format=duration,format_name", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise AudioError(f"ffprobe failed: {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout)
    stream = (data.get("streams") or [{}])[0]
    return {
        "codec": stream.get("codec_name"),
        "sample_rate": int(stream.get("sample_rate", 0)),
        "channels": int(stream.get("channels", 0)),
        "duration": float(data.get("format", {}).get("duration", 0.0)),
        "format": data.get("format", {}).get("format_name"),
    }


def silence(seconds: float, sr: int) -> np.ndarray:
    return np.zeros(max(0, int(round(seconds * sr))), dtype=np.float64)


def concat(chunks: list[np.ndarray], sr: int, crossfade_ms: float = 8.0) -> np.ndarray:
    """Join chunks with a short equal-power crossfade so there are no clicks at the seams."""
    chunks = [c for c in chunks if c.size]
    if not chunks:
        return np.zeros(0)
    n = int(sr * crossfade_ms / 1000)
    out = chunks[0].copy()
    for c in chunks[1:]:
        k = min(n, out.size, c.size)
        if k > 1:
            t = np.linspace(0, np.pi / 2, k)
            mixed = out[-k:] * np.cos(t) + c[:k] * np.sin(t)
            out = np.concatenate([out[:-k], mixed, c[k:]])
        else:
            out = np.concatenate([out, c])
    return out
