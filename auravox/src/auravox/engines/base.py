"""Provider-independent engine contract.

Every adapter declares what it can really do (`capabilities`) and implements `synthesize`. The shared operations
generate / generate_dialogue / analyze / align / convert / validate / export are built on top. An operation an
engine cannot do raises Unsupported: it is never faked.
"""

from __future__ import annotations

import hashlib
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import analysis

SR = 48000


class EngineError(RuntimeError):
    """The engine failed to run (crash, bad model, runtime error)."""


class Unsupported(RuntimeError):
    """The engine does not offer this capability; callers must route elsewhere or report BLOCKED."""


class MissingModel(EngineError):
    pass


@dataclass
class Synth:
    audio: np.ndarray                 # mono float32 at SR
    phonemes: list | None             # [(t0, t1, symbol)] when the engine reports timing
    alignment: str                    # "engine" | "estimated" | "none"
    meta: dict = field(default_factory=dict)


def resample(x: np.ndarray, src: int, dst: int = SR) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x.astype(np.float32)
    n = int(round(len(x) * dst / src))
    return np.interp(np.arange(n) * src / dst, np.arange(len(x)), x).astype(np.float32)


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Engine:
    name = "base"
    kind = "tts"
    license = ""
    quality_rank = 0                  # used by the router after capability filtering
    offline = True

    def capabilities(self) -> dict:
        """{'languages': [...], 'voices': [...], 'emotion': 'prosody'|'none'|..., 'ssml': bool, 'phoneme_timing': bool,
        'speakers': int, 'commercial_use': 'yes'|'no'|'check model licence'}"""
        raise NotImplementedError

    def health(self) -> tuple[str, str]:
        raise NotImplementedError

    def synthesize(self, text: str, voice: dict, controls: dict) -> Synth:
        raise NotImplementedError

    # ---------------------------------------------------------------- shared operations
    def generate(self, text: str, voice: dict, controls: dict, out: Path) -> dict:
        s = self.synthesize(text, voice, controls)
        if s.audio is None or len(s.audio) == 0:
            raise EngineError(f"{self.name} returned no audio")
        write_wav(out, s.audio)
        return {"path": str(out), "sha256": sha256(out), "phonemes": s.phonemes, "alignment": s.alignment, "engine": self.name,
                "meta": s.meta, "duration_s": round(len(s.audio) / SR, 3)}

    def generate_dialogue(self, lines: list[dict], voices: dict, out_dir: Path) -> list[dict]:
        return [self.generate(ln["text"], voices[ln["character_id"]], ln.get("controls", {}), out_dir / f"{ln['line_id']}.wav") | {
            "line_id": ln["line_id"]} for ln in lines]

    def analyze(self, path: Path, text: str | None = None, wpm: float = 150) -> dict:
        return analysis.measure(path, text, wpm)

    def align(self, text: str, voice: dict, controls: dict) -> list:
        s = self.synthesize(text, voice, controls)
        if not s.phonemes:
            raise Unsupported(f"{self.name} gives no phoneme timing")
        return s.phonemes

    def convert(self, src: Path, target_voice: dict, out: Path) -> dict:
        raise Unsupported(f"{self.name} cannot convert one voice into another (no speech-to-speech model installed)")

    def validate(self, path: Path, text: str | None = None, wpm: float = 150) -> dict:
        m = self.analyze(path, text, wpm)
        return {"status": "PASS" if not analysis.blocking(m) else "FAIL", "metrics": m}

    def export(self, src: Path, out: Path, fmt: str = "wav", sr: int = SR, loudness: float | None = None) -> Path:
        af = [f"loudnorm=I={loudness}:TP=-1.5:LRA=11"] if loudness is not None else []
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)] + (["-af", ",".join(af)] if af else []) + ["-ar", str(sr)]
        cmd += {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "flac": ["-c:a", "flac"], "ogg": ["-c:a", "libvorbis", "-q:a", "6"],
                "wav": ["-c:a", "pcm_s16le"]}[fmt]
        subprocess.run(cmd + [str(out)], check=True)
        return out
