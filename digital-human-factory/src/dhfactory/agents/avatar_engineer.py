from __future__ import annotations

import asyncio

from ..pipeline import cost_guard
from ..state import ProductionState
from .base import AgentResult, BaseAgent

PROVIDER_ARGS = {"heygen": ("avatar_id", "voice_id"), "did": ("source_url", "voice_id"), "synthesia": ("avatar",)}


class AvatarEngineerAgent(BaseAgent):
    name = "avatar-engineer"
    description = "Reference images, talking-avatar generation and lip sync through the configured avatar provider."

    async def references(self, state: ProductionState) -> AgentResult:
        pname = state.providers.get("image", "mock")
        prov = self.ctx.provider(pname)
        est = cost_guard.authorize(state, prov, "image", 1, self.ctx.settings.dhf_max_spend_usd)
        char = state.character
        out_dir = self.ctx.root / "reference-images" / char.character_id
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt = (f"Photorealistic studio portrait, head and shoulders, of a fictional person: {char.anchor()}. "
                  "Neutral grey seamless backdrop, soft key light, 85mm lens, natural skin texture, looking at camera.")
        out = out_dir / "front.png"
        await asyncio.to_thread(prov.image, prompt, out, (1080, 1920))
        state.reference_images = [str(out)]
        return AgentResult(status="success", artifact_paths=[str(out)], metadata={"provider": pname, "prompt": prompt}, cost_usd=est)

    async def body(self, state: ProductionState) -> AgentResult:
        """STEP 8: body movement / expressions only where the provider really does it."""
        pname = state.providers.get("avatar")
        supported = {"heygen": "provider avatar includes natural idle body and head motion", "synthesia": "provider avatar gestures"}
        if pname in supported:
            return AgentResult(status="success", metadata={"provider": pname, "support": supported[pname]})
        return AgentResult(status="skipped", metadata={"reason": f"{pname} has no body/expression control here; not faked"})

    async def lip_sync(self, state: ProductionState) -> AgentResult:
        """STEP 9: confirm who did the lip sync and that clip length matches the speech."""
        from pathlib import Path

        from ..media import ffprobe

        clip = Path(state.video_clips[0])
        dur = float(ffprobe.probe(clip)["format"]["duration"])
        speech = state.audio_manifest.get("duration")
        meta = {"provider": state.providers.get("avatar"), "clip_seconds": round(dur, 3), "speech_seconds": speech}
        if state.providers.get("avatar") in ("heygen", "did", "synthesia"):
            meta["lip_sync"] = "performed by the provider from the script (its own voice timing)"
            return AgentResult(status="success", metadata=meta)
        if speech and abs(dur - speech) > 0.25:
            return AgentResult(status="failed", metadata=meta, error=f"clip {dur:.2f}s vs speech {speech:.2f}s")
        meta["lip_sync"] = "none: the mock avatar has no mouth; only duration alignment is checked"
        return AgentResult(status="success", metadata=meta)

    async def run(self, state: ProductionState, step: str) -> AgentResult:
        pname = state.providers.get("avatar", "mock")
        prov = self.ctx.provider(pname)
        prov.require_key()
        script = " ".join(s.text for s in state.scenes)
        seconds = state.audio_manifest.get("duration") or sum(s.est_seconds for s in state.scenes)
        est = 0.0 if state.paid_jobs.get(step) else cost_guard.authorize(state, prov, "avatar", seconds, self.ctx.settings.dhf_max_spend_usd)
        cfg = self.ctx.presenter.get(pname) or {}
        missing = [k for k in PROVIDER_ARGS.get(pname, ()) if not cfg.get(k)]
        if missing:
            return AgentResult(status="blocked", error=f"configuration/presenter.json: {pname}.{', '.join(missing)} missing")
        out = self.ctx.root / "scenes" / state.job_id / "avatar.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        audio = state.audio_manifest.get("audio")
        kwargs = {k: cfg[k] for k in cfg if k in ("avatar_id", "voice_id", "source_url", "avatar", "background", "test")}
        if state.paid_jobs.get(step):
            kwargs["resume_job_id"] = state.paid_jobs[step]
        from pathlib import Path

        res = await asyncio.to_thread(prov.talking_video, script, Path(audio) if audio else None, out, state.resolution, seconds, **kwargs)
        if res.provider_job_id:
            state.paid_jobs[step] = res.provider_job_id
        state.video_clips = [str(res.video)]
        return AgentResult(status="success", artifact_paths=[str(res.video)], cost_usd=res.cost_usd if res.cost_usd is not None else est,
                           metadata={"provider": res.provider, "lip_sync": res.lip_sync, "job": res.provider_job_id, **res.meta})
