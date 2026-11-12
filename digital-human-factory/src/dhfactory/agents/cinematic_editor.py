from __future__ import annotations

import asyncio
from pathlib import Path

from ..media import ffmpeg, ffprobe
from ..media.subtitles import write_srt
from ..state import ProductionState
from .base import AgentResult, BaseAgent


class CinematicEditorAgent(BaseAgent):
    name = "cinematic-editor"
    description = "Assembles scenes with FFmpeg, adds captions, music bed, grade and loudness, and renders the final MP4."

    async def run(self, state: ProductionState, step: str) -> AgentResult:
        if not state.video_clips:
            return AgentResult(status="blocked", error="no avatar clip to edit")
        work = self.ctx.root / "scenes" / state.job_id
        w, h = state.resolution
        norm = [await asyncio.to_thread(ffmpeg.normalize, Path(c), work / f"norm_{i}.mp4", w, h) for i, c in enumerate(state.video_clips)]
        assembled = norm[0] if len(norm) == 1 else await asyncio.to_thread(ffmpeg.concat, norm, work / "assembled.mp4", work)
        dur = float(ffprobe.probe(assembled)["format"]["duration"])
        cues = state.audio_manifest.get("cues") or []
        if cues and state.audio_manifest.get("duration"):
            k = dur / max(0.01, state.audio_manifest["duration"]) if state.providers.get("avatar") != "mock" else 1.0
            cues = [{"text": c["text"], "start": c["start"] * k, "end": min(dur, c["end"] * k)} for c in cues]
        else:
            per = dur / max(1, len(state.scenes))
            cues = [{"text": s.text, "start": i * per, "end": (i + 1) * per} for i, s in enumerate(state.scenes)]
        srt = write_srt(cues, self.ctx.root / "rendered-videos" / state.job_id / "captions.srt")
        music = self.ctx.presenter.get("music")
        out = self.ctx.root / "rendered-videos" / state.job_id / "final.mp4"
        await asyncio.to_thread(ffmpeg.finish, assembled, out, srt, Path(music) if music else None)
        state.final_video = str(out)
        return AgentResult(status="success", artifact_paths=[str(out), str(srt)], metadata={"assembled_seconds": round(dur, 3), "captions": len(cues)})
