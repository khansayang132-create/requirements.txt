"""D-ID talking heads over REST (no official Python SDK used).

Auth: header 'Authorization: Basic <DID_API_KEY>' (the key as D-ID issues it). Endpoints (D-ID API docs):
  GET  /credits         read-only balance
  POST /talks           source_url (a portrait you own or a generated fictional one) + text script; D-ID lip-syncs
  GET  /talks/{id}      poll; result_url when status == "done"
"""

from __future__ import annotations

from pathlib import Path

from . import _http
from .base import ClipResult, Provider, register

BASE = "https://api.d-id.com"


@register
class DIDProvider(Provider):
    name = "did"
    capabilities = frozenset({"avatar"})
    env_var = "DID_API_KEY"

    def _h(self) -> dict:
        return {"Authorization": f"Basic {self.require_key()}", "Accept": "application/json"}

    def health(self, client=None) -> dict:
        data = _http.request(self.name, "GET", f"{BASE}/credits", headers=self._h(), timeout=self.settings.http_timeout, client=client)
        return {"ok": True, "remaining": data.get("remaining"), "total": data.get("total")}

    def talking_video(self, text: str, audio: Path | None, out: Path, size: tuple[int, int], duration: float, *, source_url: str,
                      voice_id: str = "en-US-JennyNeural", client=None, sleep=None, resume_job_id: str | None = None) -> ClipResult:
        h = self._h()
        job = resume_job_id
        if not job:
            body = {"source_url": source_url, "script": {"type": "text", "input": text, "provider": {"type": "microsoft", "voice_id": voice_id}}}
            job = _http.request(self.name, "POST", f"{BASE}/talks", headers=h, timeout=self.settings.http_timeout, client=client, json=body).get("id")
        data = _http.poll(lambda: _http.request(self.name, "GET", f"{BASE}/talks/{job}", headers=h, timeout=self.settings.http_timeout, client=client),
                          done=lambda d: d.get("status") == "done", failed=lambda d: d.get("status") in ("error", "rejected"),
                          **({"sleep": sleep} if sleep else {}))
        _http.download(data["result_url"], out, client=client)
        return ClipResult(video=out, provider=self.name, provider_job_id=job, lip_sync="provider", meta={"source_url": source_url})
