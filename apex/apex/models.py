"""Validated data models for the APEX production pipeline.

Every stage reads and writes these models as JSON, so a malformed spec is
rejected before any expensive work (rendering, TTS) starts.
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AspectRatio = Literal["9:16", "1:1", "16:9"]
Language = Literal["id", "en"]

# Visual templates the procedural Blender renderer actually implements.
# A scene that names anything else is rejected at storyboard validation.
SCENE_TEMPLATES = ("hero_coin", "coffee_cup", "coin_stack", "bar_chart", "piggy_bank")
CAMERA_MOVES = ("static", "dolly_in", "dolly_out", "orbit_left", "orbit_right", "crane_up")


class ProductionSpec(BaseModel):
    """What the owner asked for, plus explicit defaults for everything else."""

    topic: str = Field(min_length=3)
    audience: str = "general Indonesian social media users"
    objective: str = "educate"
    emotion: str = "curious, then motivated"
    platform: Literal["tiktok", "youtube_shorts", "instagram_reels", "generic"] = "tiktok"
    language: Language = "id"
    target_seconds: float = Field(30.0, gt=5, le=180)
    tolerance_seconds: float = Field(3.0, ge=0, le=15)
    aspect_ratio: AspectRatio = "9:16"
    visual_mode: Literal["premium_stylized_3d"] = "premium_stylized_3d"
    call_to_action: str = ""


class ScriptScene(BaseModel):
    scene_id: str = Field(pattern=r"^s\d{2}$")
    purpose: str = Field(min_length=3)
    narration: str = Field(min_length=1)
    on_screen_text: str = ""
    template: str
    camera_move: str = "dolly_in"
    params: dict = Field(default_factory=dict)
    music_cue: str = ""

    @field_validator("template")
    @classmethod
    def _known_template(cls, v: str) -> str:
        if v not in SCENE_TEMPLATES:
            raise ValueError(f"unknown template {v!r}; implemented: {', '.join(SCENE_TEMPLATES)}")
        return v

    @field_validator("camera_move")
    @classmethod
    def _known_move(cls, v: str) -> str:
        if v not in CAMERA_MOVES:
            raise ValueError(f"unknown camera_move {v!r}; implemented: {', '.join(CAMERA_MOVES)}")
        return v


class Script(BaseModel):
    """A versioned script. Downstream assets reference `version_hash`."""

    title: str = Field(min_length=3)
    concept: str = Field(min_length=3)
    hook: str = Field(min_length=3)
    scenes: list[ScriptScene] = Field(min_length=2, max_length=20)
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    thumbnail_concept: str = ""
    provenance: str = Field(min_length=3, description="Who/what wrote this script and how")

    @model_validator(mode="after")
    def _unique_ids(self) -> "Script":
        ids = [s.scene_id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene_id values must be unique")
        return self

    @property
    def version_hash(self) -> str:
        body = json.dumps(self.model_dump(exclude={"provenance"}), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(body.encode()).hexdigest()[:12]


class SceneSpec(BaseModel):
    """Machine-readable shot specification produced by the storyboard stage."""

    scene_id: str
    scene_order: int = Field(ge=0)
    start_time: float = Field(ge=0)
    end_time: float
    duration: float = Field(gt=0)
    narrative_purpose: str
    narration_text: str
    subtitle_text: str
    on_screen_text: str = ""
    template: str
    camera_move: str
    params: dict = Field(default_factory=dict)
    animation_method: Literal["procedural_3d_blender"] = "procedural_3d_blender"
    transition_in: Literal["cut", "fade"] = "cut"
    transition_out: Literal["cut", "fade"] = "cut"
    music_cue: str = ""
    generation_status: Literal["pending", "rendered", "failed"] = "pending"
    output_asset_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _times_consistent(self) -> "SceneSpec":
        if abs((self.end_time - self.start_time) - self.duration) > 1e-3:
            raise ValueError(f"{self.scene_id}: end_time - start_time must equal duration")
        return self


class Storyboard(BaseModel):
    script_version: str
    fps: int = Field(gt=0, le=60)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    scenes: list[SceneSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _contiguous(self) -> "Storyboard":
        t = 0.0
        for i, s in enumerate(self.scenes):
            if s.scene_order != i:
                raise ValueError("scene_order must be 0..n-1 in list order")
            if abs(s.start_time - t) > 1e-3:
                raise ValueError(f"{s.scene_id}: gap or overlap at {t:.3f}s")
            t = s.end_time
        return self

    @property
    def total_seconds(self) -> float:
        return self.scenes[-1].end_time


class JobState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_PROVIDER = "WAITING_FOR_PROVIDER"
    RETRYING = "RETRYING"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}

ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.CREATED: {JobState.QUEUED, JobState.CANCELLED},
    JobState.QUEUED: {JobState.RUNNING, JobState.CANCELLED},
    JobState.RUNNING: {JobState.WAITING_FOR_PROVIDER, JobState.RETRYING, JobState.QUALITY_REVIEW,
                       JobState.FAILED, JobState.CANCELLED, JobState.QUEUED},
    JobState.WAITING_FOR_PROVIDER: {JobState.RUNNING, JobState.RETRYING, JobState.FAILED, JobState.CANCELLED},
    JobState.RETRYING: {JobState.QUEUED, JobState.FAILED, JobState.CANCELLED},
    JobState.QUALITY_REVIEW: {JobState.COMPLETED, JobState.RETRYING, JobState.FAILED},
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}
