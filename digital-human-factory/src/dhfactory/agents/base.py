"""Agent contract: typed state in, typed AgentResult out. Agents never talk in prose."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from ..config import Settings
from ..providers.base import Provider, get_provider
from ..state import ProductionState


class AgentResult(BaseModel):
    status: str  # "success" | "failed" | "blocked" | "blocked_pending_approval" | "skipped"
    artifact_paths: list[str] = []
    metadata: dict = {}
    error: str | None = None
    cost_usd: float = 0.0


@dataclass
class Context:
    settings: Settings
    job_dir: Path
    presenter: dict = field(default_factory=dict)
    provider_overrides: dict[str, Provider] = field(default_factory=dict)   # tests inject fakes here

    @property
    def root(self) -> Path:
        return self.settings.root

    def provider(self, name: str) -> Provider:
        return self.provider_overrides.get(name) or get_provider(name, self.settings)

    @classmethod
    def for_job(cls, settings: Settings, job_id: str) -> Context:
        p = settings.root / "configuration" / "presenter.json"
        presenter = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        return cls(settings=settings, job_dir=settings.root / "jobs" / job_id, presenter=presenter)


class BaseAgent(ABC):
    name: str = ""
    description: str = ""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    @abstractmethod
    async def run(self, state: ProductionState, step: str) -> AgentResult:
        ...
