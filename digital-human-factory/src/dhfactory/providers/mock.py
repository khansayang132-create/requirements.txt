"""Mock provider: free, offline, deterministic — for tests and dry runs ONLY.

Every artifact it makes is labelled MOCK (on screen and in metadata). QC reports a mock-made video as
NOT a real production, so a dry run can never be mistaken for a generated presenter.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

from ..media import ffmpeg
from .base import ClipResult, Provider, VoiceResult, register

WORDS_PER_SECOND = 2.6


@register
class MockProvider(Provider):
    name = "mock"
    capabilities = frozenset({"voice", "avatar", "image", "video"})
    paid = False

    def configured(self) -> bool:
        return True

    def require_key(self) -> str:
        return "mock"

    def health(self) -> dict:
        return {"ok": True, "detail": "offline mock; produces labelled placeholder media"}

    def estimate_usd(self, capability: str, seconds: float) -> float:
        return 0.0

    def tts(self, cues_text: list[str], out: Path, language: str = "en") -> VoiceResult:
        sr, t, cues, samples = 48000, 0.0, [], []
        for text in cues_text:
            d = max(1.0, len(text.split()) / WORDS_PER_SECOND)
            n = int(d * sr)
            for i in range(n):           # soft syllable-rate tone so loudness and sync checks have real signal
                env = 0.5 + 0.5 * math.sin(2 * math.pi * 4 * i / sr)
                samples.append(int(6000 * env * math.sin(2 * math.pi * 180 * i / sr)))
            cues.append({"text": text, "start": round(t, 3), "end": round(t + d, 3)})
            t += d
            samples.extend([0] * int(0.25 * sr))
            t += 0.25
        out.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(b"".join(int(s).to_bytes(2, "little", signed=True) for s in samples))
        return VoiceResult(audio=out, duration=round(t, 3), cues=cues, provider=self.name, cost_usd=0.0, timing_source="estimated")

    def image(self, prompt: str, out: Path, size: tuple[int, int]) -> Path:
        w, h = size
        ffmpeg.run(["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0=0x3a3f4a:c1=0x6b7280:d=1", "-frames:v", "1",
                    "-vf", "drawtext=text='MOCK REFERENCE':fontcolor=white:fontsize=48:x=(w-tw)/2:y=(h-th)/2", str(out)])
        return out

    def talking_video(self, text: str, audio: Path | None, out: Path, size: tuple[int, int], duration: float, **_) -> ClipResult:
        w, h = size
        args = ["-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=30:d={duration:.3f}"]
        if audio:
            args += ["-i", str(audio)]
        else:
            args += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration:.3f}"]
        args += ["-vf", "drawtext=text='MOCK - not a real presenter':fontcolor=white:fontsize=44:box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h*0.12",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(out)]
        ffmpeg.run(args)
        return ClipResult(video=out, provider=self.name, lip_sync="none", cost_usd=0.0, meta={"mock": True})
