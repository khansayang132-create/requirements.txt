"""HeyGen talking avatars over its REST API (no official Python SDK is published; PyPI 'heygen' 0.0.0 is not used).

Auth: header X-Api-Key = HEYGEN_API_KEY. Endpoints used (HeyGen API v2 docs; not reachable from the build sandbox):
  GET  /v2/user/remaining_quota        read-only health/balance
  POST /v2/video/generate              avatar + text-to-speech, HeyGen does the lip sync
  GET  /v1/video_status.get?video_id=  poll; returns video_url when completed
The avatar and voice ids come from configuration/presenter.json (stock avatars of consenting actors, or the owner's own).
"""

from __future__ import annotations

from pathlib import Path

from . import _http
from .base import ClipResult, Provider, register

BASE = "https://api.heygen.com"


@register
class HeyGenProvider(Provider):
    name = "heygen"
    capabilities = frozenset({"avatar"})
    env_var = "HEYGEN_API_KEY"

    def _h(self) -> dict:
        return {"X-Api-Key": self.require_key(), "Accept": "application/json"}

    def health(self, client=None) -> dict:
        data = _http.request(self.name, "GET", f"{BASE}/v2/user/remaining_quota", headers=self._h(), timeout=self.settings.http_timeout, client=client)
        return {"ok": True, "remaining_quota": (data.get("data") or {}).get("remaining_quota")}

    def talking_video(self, text: str, audio: Path | None, out: Path, size: tuple[int, int], duration: float, *, avatar_id: str, voice_id: str,
                      background: str = "#e9e9ec", client=None, sleep=None, resume_job_id: str | None = None) -> ClipResult:
        h = self._h()
        job = resume_job_id
        if not job:
            body = {"video_inputs": [{"character": {"type": "avatar", "avatar_id": avatar_id, "avatar_style": "normal"},
                                      "voice": {"type": "text", "input_text": text, "voice_id": voice_id},
                                      "background": {"type": "color", "value": background}}],
                    "dimension": {"width": size[0], "height": size[1]}}
            data = _http.request(self.name, "POST", f"{BASE}/v2/video/generate", headers=h, timeout=self.settings.http_timeout, client=client, json=body)
            job = (data.get("data") or {}).get("video_id")
        status = _http.poll(lambda: (_http.request(self.name, "GET", f"{BASE}/v1/video_status.get", headers=h, timeout=self.settings.http_timeout,
                                                   client=client, params={"video_id": job}).get("data") or {}),
                            done=lambda d: d.get("status") == "completed", failed=lambda d: d.get("status") == "failed",
                            **({"sleep": sleep} if sleep else {}))
        _http.download(status["video_url"], out, client=client)
        return ClipResult(video=out, provider=self.name, provider_job_id=job, lip_sync="provider", meta={"avatar_id": avatar_id, "voice_id": voice_id})
