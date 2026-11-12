"""LivePortrait / SadTalker (local GPU models). Not installed: no CUDA GPU here, and their weights/licences must be
reviewed per use (SadTalker code is Apache-2.0 but depends on third-party face models; LivePortrait weights have
their own terms). This adapter reports exactly that instead of pretending."""

from __future__ import annotations

import shutil

from ..errors import ProviderNotConfigured
from .base import Provider, register


@register
class LocalGPUProvider(Provider):
    name = "local_gpu"
    capabilities = frozenset({"avatar"})
    paid = False

    def require_key(self) -> str:
        if not shutil.which("nvidia-smi"):
            raise ProviderNotConfigured(self.name, "no NVIDIA GPU (nvidia-smi not found); LivePortrait/SadTalker need CUDA and downloaded weights")
        raise ProviderNotConfigured(self.name, "GPU found, but LivePortrait/SadTalker are not installed; install them deliberately after reviewing licences")

    def health(self) -> dict:
        self.require_key()
        return {}
