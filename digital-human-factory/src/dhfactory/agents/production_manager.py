from __future__ import annotations

import json
from pathlib import Path

from ..pipeline.analyze import split_scenes
from ..state import ProductionState
from .base import AgentResult, BaseAgent


class ProductionManagerAgent(BaseAgent):
    name = "production-manager"
    description = "Owns the pipeline graph: assigns steps to agents, enforces the spend gate, resumes jobs and reports results."

    async def analyze(self, state: ProductionState) -> AgentResult:
        state.scenes = split_scenes(state.script)
        est = sum(s.est_seconds for s in state.scenes)
        return AgentResult(status="success", metadata={"scenes": len(state.scenes), "estimated_seconds": round(est, 2)})

    async def export(self, state: ProductionState) -> AgentResult:
        final = Path(state.final_video).resolve()
        return AgentResult(status="success", artifact_paths=[str(final)], metadata={"final_video": str(final), "qc": state.qc_status})

    async def run(self, state: ProductionState, step: str) -> AgentResult:
        from ..pipeline.graph import run_graph
        from . import ALL_AGENTS

        agents = {cls.name: cls(self.ctx) for cls in ALL_AGENTS if cls is not ProductionManagerAgent}
        agents[self.name] = self
        path = self.ctx.job_dir / "state.json"
        await run_graph(state, agents, lambda s: s.save(path))
        report = self.report(state)
        out = self.ctx.job_dir / "production_report.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return AgentResult(status="success" if report["final_video"] else "blocked", artifact_paths=[str(out)], metadata=report)

    def report(self, state: ProductionState) -> dict:
        return {"job_id": state.job_id, "providers": state.providers, "spend_approved": state.spend_approved, "spent_usd": state.spent_usd,
                "qc": state.qc_status, "final_video": state.final_video if state.steps.get("14_export") and state.steps["14_export"].status == "success" else None,
                "steps": {k: {"status": v.status, "agent": v.agent, "detail": v.detail, "artifacts": v.artifacts, "cost_usd": v.cost_usd}
                          for k, v in state.steps.items()}}
