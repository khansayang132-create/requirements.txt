"""Provider protocol. Every adapter raises ProviderNotConfigured when its credentials (or tool) are missing —
never a silent fallback, never a fake asset."""

from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..errors import ProviderNotConfigured


class Provider:
    name = "base"
    capabilities: frozenset[str] = frozenset()
    paid = True
    secret_field: str | None = None
    env_name: str = ""

    def __init__(self, settings: Settings):
        self.settings = settings

    def key(self) -> str:
        v = self.settings.secret(self.secret_field) if self.secret_field else None
        if not v:
            raise ProviderNotConfigured(self.name, f"set {self.env_name} in the environment or .env")
        return v

    def health(self) -> dict:
        """Read-only check (no spend)."""
        self.key()
        return {"ok": True, "detail": "credentials present (no read-only endpoint called)"}

    def estimate_usd(self, capability: str, amount: float) -> float | None:
        import json

        p = self.settings.root / "configuration" / "pricing.json"
        data = json.loads(p.read_text()) if p.is_file() else {}
        e = (data.get(self.name) or {}).get(capability) or {}
        return None if e.get("usd_per_unit") is None else round(float(e["usd_per_unit"]) * amount, 4)

    def image(self, prompt: str, out: Path, size: tuple[int, int], reference: Path | None = None) -> Path:
        raise NotImplementedError

    def image_to_video(self, image: Path, prompt: str, out: Path, duration: int = 5, resume_job_id: str | None = None):
        raise NotImplementedError


REGISTRY: dict[str, type[Provider]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


def get_provider(name: str, settings: Settings) -> Provider:
    from . import adapters  # noqa: F401

    if name not in REGISTRY:
        raise KeyError(f"unknown provider {name!r}; known: {', '.join(sorted(REGISTRY))}")
    return REGISTRY[name](settings)
