"""Adapters for the external providers. All verified in this session against the installed packages / CLIs:

  runway      official SDK `runwayml` (RunwayML(api_key).image_to_video.create, tasks.retrieve)
  flux        BFL REST: POST https://api.bfl.ai/v1/<model> with header x-key, poll `polling_url` until Ready, download result.sample
  comfyui     official SDK `comfy-sdk` (Comfy(api_key).run(workflow)); COMFY_API_KEY / COMFY_BASE_URL
  higgsfield  official SDK `higgsfield-client` (subscribe(application, arguments)); HF_KEY or HF_API_KEY + HF_API_SECRET
  kling       REST (no official Python SDK on PyPI): JWT (HS256) from KLING_ACCESS_KEY + KLING_SECRET_KEY, Bearer auth
  elevenlabs  official SDK `elevenlabs` (text_to_speech.convert_with_timestamps)
  blender     local CLI `blender --background --python`, if installed

Provider hosts were not reachable from the build sandbox, so request shapes for flux and kling follow their public
docs and are covered by mocked tests only; the first live call confirms them.
"""

from __future__ import annotations

import base64
import mimetypes
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from ..errors import ProviderError, ProviderNotConfigured
from .base import Provider, register


def _download(url: str, out: Path, client: httpx.Client | None = None) -> Path:
    c = client or httpx.Client(timeout=300, follow_redirects=True)
    try:
        r = c.get(url)
        r.raise_for_status()
        out.write_bytes(r.content)
    finally:
        if client is None:
            c.close()
    return out


def data_uri(path: Path) -> str:
    return f"data:{mimetypes.guess_type(path.name)[0] or 'image/png'};base64,{base64.b64encode(path.read_bytes()).decode()}"


@register
class RunwayProvider(Provider):
    name, capabilities, secret_field, env_name = "runway", frozenset({"image", "video"}), "runwayml_api_secret", "RUNWAYML_API_SECRET"

    def client(self):
        from runwayml import RunwayML

        return RunwayML(api_key=self.key())

    def health(self, client=None) -> dict:
        org = (client or self.client()).organization.retrieve()
        return {"ok": True, "credit_balance": getattr(org, "credit_balance", None)}

    def _wait(self, c, task_id, sleep=time.sleep):
        for _ in range(360):
            t = c.tasks.retrieve(task_id)
            if t.status == "SUCCEEDED":
                return t.output[0]
            if t.status in ("FAILED", "CANCELLED"):
                raise ProviderError(self.name, f"task {t.status}")
            sleep(5)
        raise ProviderError(self.name, "timed out", transient=True)

    def image_to_video(self, image, prompt, out, duration=5, resume_job_id=None, client=None, sleep=time.sleep):
        c = client or self.client()
        job = resume_job_id or c.image_to_video.create(model="gen4_turbo", prompt_image=data_uri(image), prompt_text=prompt,
                                                       ratio="720:1280", duration=duration).id
        _download(self._wait(c, job, sleep), out)
        return {"video": str(out), "job_id": job}


@register
class FluxProvider(Provider):
    name, capabilities, secret_field, env_name = "flux", frozenset({"image"}), "bfl_api_key", "BFL_API_KEY"
    base = "https://api.bfl.ai/v1"

    def image(self, prompt, out, size, reference=None, model="flux-kontext-pro", client=None, sleep=time.sleep):
        c = client or httpx.Client(timeout=60)
        body = {"prompt": prompt, "aspect_ratio": "9:16" if size[1] > size[0] else "16:9"}
        if reference:
            body["input_image"] = base64.b64encode(reference.read_bytes()).decode()   # keeps the character from the reference
        r = c.post(f"{self.base}/{model}", headers={"x-key": self.key(), "accept": "application/json"}, json=body)
        if r.status_code in (401, 403):
            raise ProviderNotConfigured(self.name, f"key rejected (HTTP {r.status_code})")
        r.raise_for_status()
        poll = r.json()["polling_url"]
        for _ in range(240):
            d = c.get(poll, headers={"x-key": self.key()}).json()
            if d.get("status") == "Ready":
                return _download(d["result"]["sample"], out, c)
            if d.get("status") in ("Error", "Failed", "Content Moderated", "Request Moderated"):
                raise ProviderError(self.name, str(d.get("status")))
            sleep(1.5)
        raise ProviderError(self.name, "timed out", transient=True)


@register
class ComfyProvider(Provider):
    name, capabilities, secret_field, env_name = "comfyui", frozenset({"image", "video"}), "comfy_api_key", "COMFY_API_KEY"

    def run_workflow(self, workflow: dict, out_dir: Path) -> list[str]:
        from comfy_sdk import Comfy

        with Comfy(api_key=self.key()) as c:
            job = c.run(workflow)
            paths = []
            for i, o in enumerate(getattr(job, "outputs", []) or []):
                p = out_dir / f"comfy_{i}{Path(getattr(o, 'filename', 'out.png')).suffix or '.png'}"
                p.write_bytes(o.read() if hasattr(o, "read") else bytes(o))
                paths.append(str(p))
            return paths


@register
class HiggsfieldProvider(Provider):
    name, capabilities, env_name = "higgsfield", frozenset({"image", "video"}), "HF_KEY (or HF_API_KEY + HF_API_SECRET)"

    def key(self) -> str:
        s = self.settings
        k = s.secret("hf_key") or (f"{s.secret('hf_api_key')}:{s.secret('hf_api_secret')}" if s.secret("hf_api_key") and s.secret("hf_api_secret") else None)
        if not k:
            raise ProviderNotConfigured(self.name, f"set {self.env_name}")
        return k

    def image(self, prompt, out, size, reference=None, application="higgsfield-ai/soul/v2/standard", subscribe=None):
        import os

        os.environ.setdefault("HF_KEY", self.key())
        if subscribe is None:
            import higgsfield_client

            subscribe = higgsfield_client.subscribe
        res = subscribe(application, arguments={"prompt": prompt, "aspect_ratio": "9:16" if size[1] > size[0] else "16:9"})
        url = _first_url(res)
        if not url:
            raise ProviderError(self.name, "no image URL in result")
        return _download(url, out)


@register
class KlingProvider(Provider):
    name, capabilities, env_name = "kling", frozenset({"video"}), "KLING_ACCESS_KEY + KLING_SECRET_KEY"
    base = "https://api-singapore.klingai.com"

    def key(self) -> str:
        ak, sk = self.settings.secret("kling_access_key"), self.settings.secret("kling_secret_key")
        if not (ak and sk):
            raise ProviderNotConfigured(self.name, f"set {self.env_name}")
        import hashlib
        import hmac
        import json as _json

        now = int(time.time())
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
        head = b64(_json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = b64(_json.dumps({"iss": ak, "exp": now + 1800, "nbf": now - 5}, separators=(",", ":")).encode())
        sig = b64(hmac.new(sk.encode(), head + b"." + body, hashlib.sha256).digest())
        return (head + b"." + body + b"." + sig).decode()

    def image_to_video(self, image, prompt, out, duration=5, resume_job_id=None, client=None, sleep=time.sleep):
        c = client or httpx.Client(timeout=60)
        h = {"Authorization": f"Bearer {self.key()}", "Content-Type": "application/json"}
        job = resume_job_id
        if not job:
            r = c.post(f"{self.base}/v1/videos/image2video", headers=h,
                       json={"model_name": "kling-v2-1", "image": base64.b64encode(image.read_bytes()).decode(), "prompt": prompt,
                             "duration": str(duration), "mode": "std"})
            r.raise_for_status()
            job = r.json()["data"]["task_id"]
        for _ in range(360):
            d = c.get(f"{self.base}/v1/videos/image2video/{job}", headers=h).json()["data"]
            if d.get("task_status") == "succeed":
                _download(d["task_result"]["videos"][0]["url"], out, c)
                return {"video": str(out), "job_id": job}
            if d.get("task_status") == "failed":
                raise ProviderError(self.name, d.get("task_status_msg", "failed"))
            sleep(5)
        raise ProviderError(self.name, "timed out", transient=True)


@register
class ElevenLabsProvider(Provider):
    name, capabilities, secret_field, env_name = "elevenlabs", frozenset({"voice", "sfx"}), "elevenlabs_api_key", "ELEVENLABS_API_KEY"

    def health(self, client=None) -> dict:
        from elevenlabs.client import ElevenLabs

        sub = (client or ElevenLabs(api_key=self.key())).user.subscription.get()
        return {"ok": True, "characters_used": sub.character_count, "character_limit": sub.character_limit}


@register
class BlenderProvider(Provider):
    name, capabilities, paid = "blender", frozenset({"3d"}), False

    def key(self) -> str:
        exe = shutil.which("blender")
        if not exe:
            raise ProviderNotConfigured(self.name, "Blender is not installed (needs `blender` on PATH; a GPU for Eevee at useful speed)")
        return exe

    def health(self) -> dict:
        out = subprocess.run([self.key(), "--version"], capture_output=True, text=True, check=False, timeout=60).stdout.splitlines()
        return {"ok": True, "version": out[0] if out else "?"}

    def run_script(self, script: Path, blend: Path | None = None, timeout: int = 3600) -> str:
        args = [self.key(), "--background", *([str(blend)] if blend else []), "--python", str(script)]
        p = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
        if p.returncode:
            raise ProviderError(self.name, p.stderr[-400:])
        return p.stdout[-2000:]


@register
class LocalEngineProvider(Provider):
    """The in-house engine: free, offline, real renders (3D toon via Three.js, or 2D), voices, Foley, mix."""

    name, capabilities, paid = "local", frozenset({"image", "video", "voice", "sfx", "3d"}), False

    def key(self) -> str:
        from .. import engine

        ok, why = engine.available()
        if not ok:
            raise ProviderNotConfigured(self.name, why)
        return "local"

    def health(self) -> dict:
        from .. import engine

        self.key()
        engine.load()
        from wonderland.render import three_backend

        three, why = three_backend.available()
        return {"ok": True, "3d": three, "3d_detail": why,
                "detail": f"engine at {engine.ROOT}; 3D toon renderer {'ready' if three else 'unavailable, 2D fallback'}" + (f" ({why})" if why and not three else "")}


def _first_url(x):
    if isinstance(x, str) and x.startswith("https://"):
        return x
    if isinstance(x, dict):
        x = list(x.values())
    if isinstance(x, list):
        for v in x:
            u = _first_url(v)
            if u:
                return u
    return None
