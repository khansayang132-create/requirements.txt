"""Runway through the official SDK (`runwayml`, github.com/runwayml/sdk-python): reference stills and image-to-video.

Read-only health: organization.retrieve() (credit balance). Generation endpoints are paid and only run after the cost
guard approves them. Image inputs must be HTTPS URLs or data URIs; local files are sent as data URIs.
"""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path

from ..errors import ProviderError
from . import _http
from .base import ClipResult, Provider, register


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


@register
class RunwayProvider(Provider):
    name = "runway"
    capabilities = frozenset({"image", "video"})
    env_var = "RUNWAYML_API_SECRET"

    def client(self):
        from runwayml import RunwayML

        return RunwayML(api_key=self.require_key(), timeout=self.settings.http_timeout)

    def health(self, client=None) -> dict:
        org = (client or self.client()).organization.retrieve()
        return {"ok": True, "credit_balance": getattr(org, "credit_balance", None)}

    def _wait(self, c, task_id: str, timeout: float = 900, sleep=time.sleep) -> str:
        t0 = time.monotonic()
        while True:
            t = c.tasks.retrieve(task_id)
            if t.status == "SUCCEEDED":
                return t.output[0]
            if t.status in ("FAILED", "CANCELLED"):
                raise ProviderError(self.name, f"task {t.status}: {getattr(t, 'failure', '')}")
            if time.monotonic() - t0 > timeout:
                raise ProviderError(self.name, "timed out", transient=True)
            sleep(5)

    def image(self, prompt: str, out: Path, size: tuple[int, int], *, model: str = "gen4_image", client=None, sleep=time.sleep) -> Path:
        c = client or self.client()
        ratio = "1080:1920" if size[1] > size[0] else "1920:1080"
        task = c.text_to_image.create(model=model, prompt_text=prompt, ratio=ratio)
        _http.download(self._wait(c, task.id, sleep=sleep), out)
        return out

    def image_to_video(self, image: Path, prompt: str, out: Path, *, duration: int = 5, model: str = "gen4_turbo", client=None,
                       sleep=time.sleep, resume_job_id: str | None = None) -> ClipResult:
        c = client or self.client()
        job = resume_job_id or c.image_to_video.create(model=model, prompt_image=data_uri(image), prompt_text=prompt, ratio="720:1280",
                                                       duration=duration).id
        _http.download(self._wait(c, job, sleep=sleep), out)
        return ClipResult(video=out, provider=self.name, provider_job_id=job, lip_sync="none", meta={"model": model})
