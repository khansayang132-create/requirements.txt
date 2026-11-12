"""Typed models shared by all agents."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class Identity(BaseModel):
    species: str
    age_category: str
    personality: list[str]
    background: str
    strengths: list[str]
    weaknesses: list[str]
    emotions: str
    catchphrase: str


class VisualDesign(BaseModel):
    face: str
    eyes: str
    proportions: str
    surface: str
    clothing: str
    accessory: str
    palette: dict[str, str]                 # body, belly, inner_ear, accent, nose (hex)
    distinctive: str
    engine_body: str | None = None           # body plan the local engine draws, when it differs from the species


class AnimationDesign(BaseModel):
    walk: str
    run: str
    talk: str
    expressions: list[str]
    reactions: str
    idle: str
    signature_moves: list[str]


class CharacterSpec(BaseModel):
    character_id: str
    name: str
    role: str
    identity: Identity
    visual: VisualDesign
    animation: AnimationDesign
    voice: dict                              # provider -> profile
    relationships: dict[str, str] = Field(default_factory=dict)
    reference_sha256: dict[str, str] = Field(default_factory=dict)   # filled when the bible is rendered
    source: dict = Field(default_factory=dict)                        # where an imported character came from


class UniverseBible(BaseModel):
    universe_id: str
    title: str
    concept: str
    world: str
    tone: str
    audience: str
    world_rules: list[str]
    places: dict[str, str]                   # engine environment -> local place name
    recurring_storylines: list[str]
    episode_concepts: list[str]
    characters: list[CharacterSpec]
    originality: dict = Field(default_factory=dict)


class SceneSpec(BaseModel):
    number: int
    act: str                                  # hook, introduction, development, conflict, climax, resolution, ending
    duration: float = 0.0
    location: str
    environment: str
    characters: list[str]
    actions: dict[str, str]
    dialogue: dict                            # {"speaker", "text"}
    camera_angle: str
    camera_movement: str
    lighting: str
    background: str
    sound_effects: list[str] = Field(default_factory=list)
    music: str
    transition: str


class EpisodeScript(BaseModel):
    episode_id: str
    universe_id: str
    title: str
    theme: str
    logline: str
    moral: str
    target_seconds: int
    scenes: list[SceneSpec]
    beats: list[dict]                          # engine beat format (rendered by the local engine)
    originality: dict = Field(default_factory=dict)


class StepRecord(BaseModel):
    status: str = "pending"
    agent: str = ""
    detail: str = ""
    artifacts: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    finished_at: str | None = None


class ProductionState(BaseModel):
    job_id: str
    universe_id: str
    episode_id: str | None = None
    target_seconds: int = 60
    resolution: tuple[int, int] = (1080, 1920)
    backend: str = "auto"                      # local engine: auto | three | flat
    video_provider: str = "none"               # none | runway | kling | higgsfield
    character_hashes: dict[str, dict[str, str]] = Field(default_factory=dict)
    voice_manifest: dict = Field(default_factory=dict)
    video_clips: list[str] = Field(default_factory=list)
    final_video: str | None = None
    qc_status: str = "NOT_TESTED"
    spend_approved: bool = False
    spent_usd: float = 0.0
    paid_jobs: dict[str, str] = Field(default_factory=dict)
    steps: dict[str, StepRecord] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> ProductionState:
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, model) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = model.model_dump() if hasattr(model, "model_dump") else model
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
