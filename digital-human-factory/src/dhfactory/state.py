"""Typed domain models. Agents exchange these objects, never prose."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

StepStatus = Literal["pending", "success", "failed", "blocked", "blocked_pending_approval", "skipped"]
QCStatus = Literal["PASS", "FAIL", "BLOCKED", "NOT_TESTED"]


class SceneSpec(BaseModel):
    index: int
    text: str
    words: int
    est_seconds: float
    setting: str = "neutral studio, soft grey seamless backdrop, three-point lighting"


class CharacterSpec(BaseModel):
    character_id: str
    name: str
    fictional: bool = True
    likeness_consent: str = "original fictional character; not based on any real person"
    age_range: str
    appearance: str
    face: str
    hair: str
    skin: str
    clothing: str
    expression: str
    voice_style: str
    language: str = "en"
    consistency_rules: list[str] = Field(default_factory=list)

    def anchor(self) -> str:
        return (f"{self.name}, {self.age_range}, {self.appearance}; face: {self.face}; hair: {self.hair}; skin: {self.skin}; "
                f"wearing {self.clothing}; expression: {self.expression}")


class StepRecord(BaseModel):
    status: StepStatus = "pending"
    agent: str = ""
    provider: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    detail: str = ""
    cost_usd: float = 0.0
    finished_at: str | None = None


class ProductionState(BaseModel):
    job_id: str
    script: str
    duration_target: float = 10.0
    resolution: tuple[int, int] = (1080, 1920)
    language: str = "en"
    providers: dict[str, str] = Field(default_factory=lambda: {"voice": "mock", "avatar": "mock", "image": "mock", "video": "none"})
    scenes: list[SceneSpec] = Field(default_factory=list)
    character: CharacterSpec | None = None
    reference_images: list[str] = Field(default_factory=list)
    audio_manifest: dict = Field(default_factory=dict)
    video_clips: list[str] = Field(default_factory=list)
    final_video: str | None = None
    qc_status: QCStatus = "NOT_TESTED"
    errors: list[str] = Field(default_factory=list)
    spend_approved: bool = False
    spent_usd: float = 0.0
    steps: dict[str, StepRecord] = Field(default_factory=dict)
    paid_jobs: dict[str, str] = Field(default_factory=dict)   # step -> provider job id, so a resume never pays twice

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
