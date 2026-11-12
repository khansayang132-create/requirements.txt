"""Higgsfield through its official CLI (`@higgsfield/cli`), which must be signed in with `higgsfield auth login`.

The CLI prints JSON with --json; generation goes through `higgsfield generate create <model> ... --wait`.
Read-only health: `higgsfield account status --json`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..errors import ProviderError, ProviderNotConfigured
from . import _http
from .base import Provider, register


@register
class HiggsfieldProvider(Provider):
    name = "higgsfield"
    capabilities = frozenset({"image", "video"})

    def _cli(self, *args: str, timeout: float = 900) -> dict:
        exe = shutil.which("higgsfield")
        if not exe:
            raise ProviderNotConfigured(self.name, "install the CLI: npm install -g @higgsfield/cli")
        p = subprocess.run([exe, *args, "--json"], check=False, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            msg = (p.stderr or p.stdout)[-300:]
            if any(w in msg.lower() for w in ("login", "auth", "token", "workspace")):
                raise ProviderNotConfigured(self.name, "sign in once: higgsfield auth login (then higgsfield workspace set <id>)")
            raise ProviderError(self.name, msg)
        return json.loads(p.stdout or "{}")

    def require_key(self) -> str:
        self.health()
        return "cli"

    def health(self) -> dict:
        data = self._cli("account", "status", timeout=60)
        return {"ok": True, **{k: data.get(k) for k in ("plan", "credits", "subscription_plan_type") if k in data}}

    def image(self, prompt: str, out: Path, size: tuple[int, int], *, model: str = "nano_banana_pro") -> Path:
        ar = "9:16" if size[1] > size[0] else "16:9"
        data = self._cli("generate", "create", model, "--prompt", prompt, "--aspect_ratio", ar, "--wait")
        url = _first_url(data)
        if not url:
            raise ProviderError(self.name, "no result URL in CLI output")
        _http.download(url, out)
        return out


    def image_to_video(self, image: Path, prompt: str, out: Path, *, duration: int = 5, model: str = "kling_4_0_flash", **_):
        from .base import ClipResult

        data = self._cli("generate", "create", model, "--prompt", prompt, "--start-image", str(image), "--duration", str(duration),
                         "--aspect_ratio", "9:16", "--wait")
        url = _first_url(data)
        if not url:
            raise ProviderError(self.name, "no result URL in CLI output")
        _http.download(url, out)
        return ClipResult(video=out, provider=self.name, lip_sync="none", meta={"model": model})


def _first_url(data) -> str | None:
    if isinstance(data, str) and data.startswith("https://"):
        return data
    if isinstance(data, dict):
        for v in data.values():
            u = _first_url(v)
            if u:
                return u
    if isinstance(data, list):
        for v in data:
            u = _first_url(v)
            if u:
                return u
    return None
