"""13-step resumable production graph. State is saved after every step; finished steps are skipped on re-run; a paid
step that already has a provider job id resumes it instead of paying again; a blocked step only blocks its dependents."""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ProviderNotConfigured, SpendNotApproved, StudioError
from ..state import ProductionState, StepRecord, now


@dataclass(frozen=True)
class Step:
    name: str
    agent: str
    method: str
    deps: tuple[str, ...] = ()


STEPS = [
    Step("01_universe", "creative-director", "run"),
    Step("02_character_bibles", "character-designer", "run", ("01_universe",)),
    Step("03_episode_script", "story-writer", "run", ("01_universe",)),
    Step("04_analyze_script", "production-manager", "analyze", ("03_episode_script",)),
    Step("05_storyboard", "storyboard-artist", "run", ("04_analyze_script",)),
    Step("06_backgrounds", "animation-engineer", "backgrounds", ("05_storyboard",)),
    Step("07_voices", "voice-sound-engineer", "run", ("05_storyboard", "02_character_bibles")),
    Step("08_animation", "animation-engineer", "run", ("07_voices",)),
    Step("09_external_video_scenes", "video-generation-engineer", "run", ("02_character_bibles",)),
    Step("10_sound_mix", "voice-sound-engineer", "mix", ("08_animation",)),
    Step("11_assembly", "cinematic-editor", "run", ("10_sound_mix",)),
    Step("12_quality_control", "quality-control", "run", ("11_assembly",)),
    Step("13_export", "production-manager", "export", ("12_quality_control",)),
]


async def run_graph(state: ProductionState, agents: dict, save) -> ProductionState:
    for step in STEPS:
        rec = state.steps.get(step.name) or StepRecord(agent=step.agent)
        if rec.status in ("success", "skipped"):
            continue
        bad = [d for d in step.deps if (state.steps.get(d) or StepRecord()).status not in ("success", "skipped")]
        if bad:
            rec.status, rec.detail = "blocked", f"waiting for {', '.join(bad)}"
        else:
            try:
                res = await getattr(agents[step.agent], step.method)(state)
                rec.status, rec.artifacts, rec.cost_usd = res.status, res.artifact_paths, res.cost_usd
                rec.detail = (res.error or str(res.metadata))[:600]
                state.spent_usd = round(state.spent_usd + res.cost_usd, 4)
            except SpendNotApproved as e:
                rec.status, rec.detail = "blocked_pending_approval", str(e)
            except ProviderNotConfigured as e:
                rec.status, rec.detail = "blocked", str(e)
            except StudioError as e:
                rec.status, rec.detail = getattr(e, "status", "failed"), str(e)
            except Exception as e:  # noqa: BLE001 - recorded, never hidden
                rec.status, rec.detail = "failed", f"{type(e).__name__}: {e}"[:600]
            rec.finished_at = now()
        state.steps[step.name] = rec
        if rec.status == "failed":
            state.errors.append(f"{step.name}: {rec.detail[:200]}")
        save(state)
    return state
