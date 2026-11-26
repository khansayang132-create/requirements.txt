"""Separate a voice from background music before using a recording as a voice reference.

Music under a reference recording pulls a cloned voice lower and rougher (measured: a clone made
from a song-backed ad came out at 160 Hz; the same voice separated first came out at 187 Hz,
matching the speaker's 192 Hz). This uses UVR-MDX-NET-Voc_FT, an ONNX model from Ultimate Vocal
Remover (Anjok07, aufr33; MIT, credit requested), downloaded from a byte-for-byte Hugging Face
mirror and checked against its SHA-256 before use. Needs the neural install (torch, onnxruntime).

    python -m nova.separate <recording> <voice.wav> [--music music.wav]
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO, FILE = "aaatmy/uvr-mdx-net-onnx", "UVR-MDX-NET-Voc_FT.onnx"
SHA256 = "534b2070fcc7df514b13ef660dc8cbb328679c2374d04354a5c42bb14ecce111"
N_FFT, HOP, DIM_F, DIM_T, COMPENSATE, SR = 7680, 1024, 3072, 256, 1.021, 44100


def model_path(models_dir: Path) -> Path:
    path = models_dir / FILE
    if not path.is_file():
        from huggingface_hub import hf_hub_download
        hf_hub_download(REPO, FILE, local_dir=str(models_dir))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SHA256:
        path.unlink()
        raise RuntimeError(f"{FILE} failed its checksum ({digest}); deleted, try again")
    return path


def separate(src: str | Path, models_dir: Path) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (voice, music, sample_rate) as stereo arrays shaped (2, n)."""
    import onnxruntime as ort
    import torch
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-f", "f32le", "-ac", "2",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    mix = np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy()
    n_bins, chunk, trim = N_FFT // 2 + 1, HOP * (DIM_T - 1), N_FFT // 2
    gen = chunk - 2 * trim
    n = mix.shape[1]
    pad = gen - n % gen
    mix_p = np.concatenate([np.zeros((2, trim)), mix, np.zeros((2, pad)), np.zeros((2, trim))], 1).astype(np.float32)
    win = torch.hann_window(N_FFT, periodic=True)
    sess = ort.InferenceSession(str(model_path(models_dir)), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    outs = []
    for i in range(0, n + pad, gen):
        w = torch.from_numpy(mix_p[:, i:i + chunk])
        X = torch.stft(w, N_FFT, HOP, window=win, center=True, return_complex=True)
        X = torch.view_as_real(X).permute(0, 3, 1, 2).reshape(1, 4, n_bins, DIM_T)[:, :, :DIM_F]
        Y = torch.from_numpy(sess.run(None, {name: X.numpy()})[0])
        Y = torch.cat([Y, torch.zeros(1, 4, n_bins - DIM_F, DIM_T)], 2)
        Y = Y.reshape(2, 2, n_bins, DIM_T).permute(0, 2, 3, 1).contiguous()
        y = torch.istft(torch.view_as_complex(Y), N_FFT, HOP, window=win, center=True, length=chunk)
        outs.append(y[:, trim:-trim].numpy())
    voice = np.concatenate(outs, 1)[:, :n] * COMPENSATE
    return voice, mix - voice, SR


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m nova.separate", description=__doc__.splitlines()[0])
    ap.add_argument("recording")
    ap.add_argument("voice_out", type=Path)
    ap.add_argument("--music", type=Path, default=None)
    ap.add_argument("--models-dir", type=Path, default=Path.home() / ".nova" / "models")
    args = ap.parse_args(argv)
    import soundfile as sf
    args.models_dir.mkdir(parents=True, exist_ok=True)
    voice, music, sr = separate(args.recording, args.models_dir)
    sf.write(str(args.voice_out), voice.T, sr)
    if args.music:
        sf.write(str(args.music), music.T, sr)
    print(f"voice: {args.voice_out} ({voice.shape[1] / sr:.2f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
