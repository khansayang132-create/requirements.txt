"""Synthesia over REST (PyPI 'synthesia' is not an official package and is not used).

Auth: header 'Authorization: <SYNTHESIA_API_KEY>'. Endpoints (Synthesia API v2 docs):
  GET  /v2/videos?limit=1     read-only health
  POST /v2/videos             {"test": true, ...} makes a free watermarked test video
  GET  /v2/videos/{id}        poll; download URL when status == "complete"
"""

from __future__ import annotations

from pathlib import Path

from . import _http
from .base import ClipResult, Provider, register

BASE = "https://api.synthesia.io"


@register
class SynthesiaProvider(Provider):
    name = "synthesia"
    capabilities = frozenset({"avatar"})
    env_var = "SYNTHESIA_API_KEY"

    def _h(self) -> dict:
        return {"Authorization": self.require_key(), "Accept": "application/json"}

    def health(self, client=None) -> dict:
        _http.request(self.name, "GET", f"{BASE}/v2/videos", headers=self._h(), timeout=self.settings.http_timeout, client=client, params={"limit": 1})
        return {"ok": True}

    def talking_video(self, text: str, audio: Path | None, out: Path, size: tuple[int, int], duration: float, *, avatar: str,
                      background: str = "off_white", test: bool = True, client=None, sleep=None, resume_job_id: str | None = None) -> ClipResult:
        h = self._h()
        job = resume_job_id
        if not job:
            body = {"test": test, "title": out.stem, "aspectRatio": "9:16" if size[1] > size[0] else "16:9",
                    "input": [{"scriptText": text, "avatar": avatar, "background": background}]}
            job = _http.request(self.name, "POST", f"{BASE}/v2/videos", headers=h, timeout=self.settings.http_timeout, client=client, json=body).get("id")
        data = _http.poll(lambda: _http.request(self.name, "GET", f"{BASE}/v2/videos/{job}", headers=h, timeout=self.settings.http_timeout, client=client),
                          done=lambda d: d.get("status") == "complete", failed=lambda d: d.get("status") in ("rejected", "error"),
                          **({"sleep": sleep} if sleep else {}))
        _http.download(data["download"], out, client=client)
        return ClipResult(video=out, provider=self.name, provider_job_id=job, lip_sync="provider", meta={"avatar": avatar, "test": test})
