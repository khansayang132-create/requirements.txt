"""The production DAG: 14 steps, each owned by one agent, run in dependency order.

State is saved after every step, so `run` can be repeated: finished steps are skipped and a paid step that already
has a provider job id resumes that job instead of paying again. A blocked or failed step blocks only the steps that
depend on it; independent steps still run.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import DHFError, ProviderNotConfigured, SpendNotApproved
from ..state import ProductionState, StepRecord, now
from ..utils.logging import log
from ..utils.redaction import redact


@dataclass(frozen=True)
class Step:
    name: str
    agent: str
    method: str
    deps: tuple[str, ...] = ()


STEPS: list[Step] = [
    Step("01_analyze", "production-manager", "analyze"),
    Step("02_character", "digital-human-director", "run", ("01_analyze",)),
    Step("03_reference_images", "avatar-engineer", "references", ("02_character",)),
    Step("04_identity", "digital-human-director", "identity", ("03_reference_images",)),
    Step("05_backgrounds", "video-engineer", "backgrounds", ("01_analyze",)),
    Step("06_voice", "voice-engineer", "run", ("01_analyze",)),
    Step("07_talking_avatar", "avatar-engineer", "run", ("02_character", "06_voice")),
    Step("08_body_and_expression", "avatar-engineer", "body", ("07_talking_avatar",)),
    Step("09_lip_sync", "avatar-engineer", "lip_sync", ("07_talking_avatar",)),
    Step("10_cinematic_scenes", "video-engineer", "run", ("04_identity",)),
    Step("11_assembly_and_12_finishing", "cinematic-editor", "run", ("09_lip_sync",)),
    Step("13_quality_control", "quality-control", "run", ("11_assembly_and_12_finishing", "04_identity")),
    Step("14_export", "production-manager", "export", ("13_quality_control",)),
]


async def run_graph(state: ProductionState, agents: dict, save) -> ProductionState:
    for step in STEPS:
        rec = state.steps.get(step.name) or StepRecord(agent=step.agent)
        if rec.status in ("success", "skipped"):
            continue
        bad = [d for d in step.deps if (state.steps.get(d) or StepRecord()).status not in ("success", "skipped")]
        if bad:
            rec.status, rec.detail = "blocked", f"waiting for {', '.join(bad)}"
            state.steps[step.name] = rec
            save(state)
            continue
        agent = agents[step.agent]
        try:
            res = await getattr(agent, step.method)(state) if step.method != "run" else await agent.run(state, step.name)
            rec.status, rec.artifacts, rec.cost_usd = res.status, res.artifact_paths, res.cost_usd
            rec.provider = res.metadata.get("provider")
            rec.detail = redact(res.error or str({k: v for k, v in res.metadata.items() if k not in ("cues",)})[:600])
            state.spent_usd = round(state.spent_usd + res.cost_usd, 4)
        except SpendNotApproved as e:
            rec.status, rec.detail = "blocked_pending_approval", redact(str(e))
        except ProviderNotConfigured as e:
            rec.status, rec.detail = "blocked", redact(str(e))
        except DHFError as e:
            rec.status, rec.detail = getattr(e, "status", "failed"), redact(str(e))
        except Exception as e:  # noqa: BLE001 - a crashing step is recorded, never hidden
            rec.status, rec.detail = "failed", redact(f"{type(e).__name__}: {e}")[:600]
        rec.finished_at = now()
        state.steps[step.name] = rec
        if rec.status in ("failed",):
            state.errors.append(f"{step.name}: {rec.detail}")
        log("step", job=state.job_id, step=step.name, status=rec.status)
        save(state)
    return state
