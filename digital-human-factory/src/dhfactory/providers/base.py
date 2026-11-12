"""Provider protocol and registry.

Every provider says which capabilities it has (voice, avatar, image, video), whether it costs money, and how to
check it read-only (`health`). A provider without credentials raises ProviderNotConfigured — it never silently
falls back to another provider or to a fake result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..errors import ProviderNotConfigured


@dataclass
class VoiceResult:
    audio: Path
    duration: float
    cues: list[dict]                 # [{"text","start","end"}]
    provider: str
    cost_usd: float | None = None
    timing_source: str = "estimated"  # "provider" when the provider returned word/char timing


@dataclass
class ClipResult:
    video: Path
    provider: str
    provider_job_id: str | None = None
    lip_sync: str = "none"           # "provider" | "none"
    cost_usd: float | None = None
    meta: dict = field(default_factory=dict)


class Provider:
    name = "base"
    capabilities: frozenset[str] = frozenset()
    paid = True
    env_var: str | None = None

    def __init__(self, settings: Settings):
        self.settings = settings

    def require_key(self) -> str:
        key = self.settings.key(self.name) if self.env_var else None
        if not key:
            raise ProviderNotConfigured(self.name, f"set {self.env_var} in the environment or .env")
        return key

    def configured(self) -> bool:
        try:
            self.require_key()
            return True
        except ProviderNotConfigured:
            return False

    def health(self) -> dict:
        """Read-only call that proves credentials work. Never spends."""
        raise NotImplementedError

    def estimate_usd(self, capability: str, seconds: float) -> float | None:
        """Cost estimate from configuration/pricing.json (owner-confirmed); None = unknown."""
        from ..pipeline.cost_guard import price_for

        return price_for(self.settings.root, self.name, capability, seconds)


REGISTRY: dict[str, type[Provider]] = {}


def register(cls: type[Provider]) -> type[Provider]:
    REGISTRY[cls.name] = cls
    return cls


def get_provider(name: str, settings: Settings) -> Provider:
    from . import did, elevenlabs, heygen, higgsfield_cli, local_gpu, mock, runway, synthesia  # noqa: F401  (registration)

    if name not in REGISTRY:
        raise KeyError(f"unknown provider {name!r}; known: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[name](settings)
