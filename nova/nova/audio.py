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


def time_stretch(x: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """Change speed without changing pitch (ffmpeg atempo, WSOLA). factor 1.2 = 20% faster."""
    factor = float(np.clip(factor, 0.5, 2.0))
    if abs(factor - 1.0) < 0.01 or x.size == 0:
        return x
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        sf.write(str(src), np.clip(x, -1, 1), sr, subtype="FLOAT")
        proc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-filter:a",
                               f"atempo={factor:.4f}", str(dst)], capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise AudioError(f"time-stretch failed: {proc.stderr.strip()[:200]}")
        y, _ = sf.read(str(dst), dtype="float64")
    return to_mono(y)


def voice_tone(x: np.ndarray, sr: int, pitch_semitones: float = 0.0, soften: float = 0.0) -> np.ndarray:
    """Adjust a finished voice without a vocoder (ffmpeg rubberband): `pitch_semitones` moves the
    pitch and keeps the formants; `soften` (0-1) gives a lighter, gentler voice: formants up to
    +1 semitone, a small 3 kHz presence dip and softer highs. Length is unchanged."""
    pitch_semitones = float(np.clip(pitch_semitones, -6, 6))
    soften = float(np.clip(soften, 0.0, 1.0))
    if x.size == 0 or (abs(pitch_semitones) < 0.05 and soften < 0.01):
        return x
    total = 2 ** (pitch_semitones / 12)
    formant = 2 ** (soften / 12)
    filters = []
    if soften >= 0.01:  # move pitch and formants together by `formant`, then pitch alone by the rest
        filters.append(f"rubberband=pitch={formant:.5f}:formant=shifted:pitchq=quality")
    if abs(total / formant - 1) > 1e-4:
        filters.append(f"rubberband=pitch={total / formant:.5f}:formant=preserved:pitchq=quality")
    if soften >= 0.01:
        filters += [f"equalizer=f=3200:t=q:w=1.2:g={-1.5 * soften:.2f}",
                    f"highshelf=f=7000:g={-3.0 * soften:.2f}"]  # no de-esser: it dulled the voice by half
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        sf.write(str(src), np.clip(x, -1, 1), sr, subtype="FLOAT")
        proc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-filter:a",
                               ",".join(filters), "-ar", str(sr), str(dst)],
                              capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise AudioError(f"voice tone failed: {proc.stderr.strip()[:200]}")
        y, _ = sf.read(str(dst), dtype="float64")
    y = to_mono(y)
    return y[: x.size] if y.size >= x.size else np.pad(y, (0, x.size - y.size))
