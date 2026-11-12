from __future__ import annotations

import asyncio
import json

from ..pipeline import cost_guard
from ..state import ProductionState
from .base import AgentResult, BaseAgent


class VoiceEngineerAgent(BaseAgent):
    name = "voice-engineer"
    description = "Narration through the configured voice provider, with timings; cloned voices only with recorded authorization."

    async def run(self, state: ProductionState, step: str) -> AgentResult:
        pname = state.providers.get("voice", "mock")
        prov = self.ctx.provider(pname)
        texts = [s.text for s in state.scenes]
        est = cost_guard.authorize(state, prov, "voice", sum(len(t) for t in texts), self.ctx.settings.dhf_max_spend_usd)
        out = self.ctx.root / "audio" / state.job_id / "voice.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if pname == "elevenlabs":
            v = self.ctx.presenter.get("elevenlabs") or {}
            auth = self.ctx.root / "configuration" / "voice-authorizations.json"
            kwargs = {"voice_id": v.get("voice_id"), "model_id": v.get("model_id", "eleven_multilingual_v2"),
                      "authorized_clones": set(json.loads(auth.read_text())) if auth.is_file() else set()}
            if not kwargs["voice_id"]:
                return AgentResult(status="blocked", error="configuration/presenter.json: elevenlabs.voice_id is missing")
        res = await asyncio.to_thread(prov.tts, texts, out, state.language, **kwargs)
        manifest = {"provider": res.provider, "audio": str(res.audio), "duration": res.duration, "cues": res.cues, "timing_source": res.timing_source}
        (out.parent / "speech_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        state.audio_manifest = manifest
        return AgentResult(status="success", artifact_paths=[str(res.audio), str(out.parent / "speech_manifest.json")], metadata=manifest,
                           cost_usd=res.cost_usd if res.cost_usd is not None else est)
