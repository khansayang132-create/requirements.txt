from __future__ import annotations

import asyncio
from pathlib import Path

from ..pipeline import cost_guard
from ..state import ProductionState
from .base import AgentResult, BaseAgent


class VideoEngineerAgent(BaseAgent):
    name = "video-engineer"
    description = "Scene backgrounds and cinematic image-to-video shots (camera movement) through the configured providers."

    async def backgrounds(self, state: ProductionState) -> AgentResult:
        pname = state.providers.get("image", "mock")
        prov = self.ctx.provider(pname)
        settings = sorted({s.setting for s in state.scenes})
        est = cost_guard.authorize(state, prov, "image", len(settings), self.ctx.settings.dhf_max_spend_usd)
        out_dir = self.ctx.root / "scenes" / state.job_id / "backgrounds"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, setting in enumerate(settings):
            p = out_dir / f"bg_{i}.png"
            await asyncio.to_thread(prov.image, f"Empty {setting}, photographic, no people, shallow depth of field", p, state.resolution)
            paths.append(str(p))
        return AgentResult(status="success", artifact_paths=paths, cost_usd=est)

    async def run(self, state: ProductionState, step: str) -> AgentResult:
        pname = state.providers.get("video", "none")
        if pname == "none":
            return AgentResult(status="skipped", metadata={"reason": "no cinematic video provider selected (providers.video = none)"})
        prov = self.ctx.provider(pname)
        prov.require_key()
        if not state.reference_images:
            return AgentResult(status="blocked", error="no reference image to animate")
        est = 0.0 if state.paid_jobs.get(step) else cost_guard.authorize(state, prov, "video", 5, self.ctx.settings.dhf_max_spend_usd)
        out = self.ctx.root / "scenes" / state.job_id / "broll.mp4"
        kw = {"resume_job_id": state.paid_jobs[step]} if state.paid_jobs.get(step) and pname == "runway" else {}
        res = await asyncio.to_thread(prov.image_to_video, Path(state.reference_images[0]),
                                      "slow cinematic push-in, the presenter smiles and nods, soft studio light", out, duration=5, **kw)
        if res.provider_job_id:
            state.paid_jobs[step] = res.provider_job_id
        return AgentResult(status="success", artifact_paths=[str(res.video)], metadata={"provider": res.provider, **res.meta},
                           cost_usd=res.cost_usd if res.cost_usd is not None else est)
