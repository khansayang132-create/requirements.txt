"""Settings changed from the app (Settings page) instead of environment variables.

Saved in $NOVA_DATA_DIR/runtime.json (mode 600). A saved value overrides the environment
variable; clearing it in the app falls back to the environment again. The LLM API key is stored
Fernet-encrypted with the same key as the voice profiles and is never sent back to the browser."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from .config import Settings

PROVIDERS = {
    "off": {"name": "Off (rules only)", "base_url": "", "model": "", "needs_key": False},
    "llama.cpp": {"name": "llama.cpp (llama-server)", "base_url": "http://127.0.0.1:8080", "model": "local", "needs_key": False},
    "ollama": {"name": "Ollama", "base_url": "http://127.0.0.1:11434", "model": "gemma4:e2b", "needs_key": False},
    "lmstudio": {"name": "LM Studio", "base_url": "http://127.0.0.1:1234", "model": "", "needs_key": False},
    "vllm": {"name": "vLLM", "base_url": "http://127.0.0.1:8000", "model": "", "needs_key": False},
    "jan": {"name": "Jan", "base_url": "http://127.0.0.1:1337", "model": "", "needs_key": False},
    "koboldcpp": {"name": "KoboldCpp", "base_url": "http://127.0.0.1:5001", "model": "local", "needs_key": False},
    "custom": {"name": "Custom (OpenAI-compatible, local or cloud)", "base_url": "", "model": "", "needs_key": True},
}

PIPER_VOICE = {
    "file": "id_ID-news_tts-medium.onnx",
    "base": "https://huggingface.co/rhasspy/piper-voices/resolve/main/id/id_ID/news_tts/medium",
    "sha256": "ed8f02aa593f7af6b19acbdb8142e0da0dd72f46194eb33d38e0eb10a52597e8",
}


def validate_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("endpoint must start with http:// or https:// and include a host")
    return url.rstrip("/")


class Runtime:
    def __init__(self, settings: Settings, fernet: Fernet) -> None:
        self.settings = settings
        self.fernet = fernet
        self.path = settings.data_dir / "runtime.json"
        self.env = {k: getattr(settings, k) for k in
                    ("llm_base_url", "llm_model", "llm_api_key", "llm_thinking", "chatterbox", "piper_model")}
        self.saved = self._load()
        self.apply()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(self.saved, fh, indent=2)

    def _key(self) -> str | None:
        enc = self.saved.get("llm_api_key_enc")
        if not enc:
            return None
        try:
            return self.fernet.decrypt(enc.encode()).decode()
        except InvalidToken:
            return None

    def apply(self) -> None:
        """Overlay saved values on the environment defaults in the live Settings object."""
        s, saved = self.settings, self.saved
        llm = saved.get("llm")
        if llm is not None:
            s.llm_base_url = "" if llm.get("provider") == "off" else llm.get("base_url", "")
            s.llm_model = llm.get("model") or "local"
            s.llm_thinking = bool(llm.get("thinking"))
        else:
            s.llm_base_url, s.llm_model, s.llm_thinking = (
                self.env["llm_base_url"], self.env["llm_model"], self.env["llm_thinking"])
        key = self._key()
        s.llm_api_key = key if key is not None else self.env["llm_api_key"]
        s.chatterbox = bool(saved["chatterbox"]) if "chatterbox" in saved else self.env["chatterbox"]

    def update_llm(self, provider: str, base_url: str, model: str, api_key: str | None,
                   thinking: bool, clear_key: bool = False) -> dict:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}")
        base_url = validate_base_url(base_url) if provider != "off" else ""
        if provider != "off" and not base_url:
            raise ValueError("enter the server's endpoint address")
        self.saved["llm"] = {"provider": provider, "base_url": base_url, "model": (model or "").strip(),
                             "thinking": bool(thinking)}
        if clear_key:
            self.saved.pop("llm_api_key_enc", None)
        elif api_key:
            self.saved["llm_api_key_enc"] = self.fernet.encrypt(api_key.strip().encode()).decode()
        self._save()
        self.apply()
        return self.public()

    def set_chatterbox(self, enabled: bool) -> None:
        self.saved["chatterbox"] = bool(enabled)
        self._save()
        self.apply()

    def public(self) -> dict:
        s = self.settings
        llm = self.saved.get("llm") or {}
        provider = llm.get("provider") or ("custom" if s.llm_base_url else "off")
        return {
            "llm": {"provider": provider, "base_url": s.llm_base_url, "model": s.llm_model if s.llm_base_url else "",
                    "thinking": s.llm_thinking, "api_key_set": bool(self._key() or self.env["llm_api_key"] not in ("", "none")),
                    "source": "app" if "llm" in self.saved else ("environment" if s.llm_base_url else "none")},
            "chatterbox": {"enabled": s.chatterbox, "installed": _chatterbox_installed()},
            "piper": {"installed": Path(s.piper_model).is_file(), "path": s.piper_model},
            "providers": [{"id": k, **v} for k, v in PROVIDERS.items()],
        }


def _chatterbox_installed() -> bool:
    import importlib.util
    return importlib.util.find_spec("chatterbox") is not None


def list_models(base_url: str, api_key: str = "") -> list[str]:
    from .llm import _base_url
    headers = {"Authorization": f"Bearer {api_key}"} if api_key and api_key != "none" else {}
    resp = httpx.get(f"{_base_url(validate_base_url(base_url))}/models", headers=headers, timeout=10)
    resp.raise_for_status()
    return sorted(m["id"] for m in resp.json().get("data", []) if m.get("id"))


def explain_error(exc: Exception) -> str:
    """Plain-language cause and fix, in the spirit of the Social Stream Ninja error table."""
    if isinstance(exc, httpx.ConnectError):
        return "Can't reach the server. Is it running, and is the address and port right?"
    if isinstance(exc, httpx.TimeoutException):
        return "The server took too long. The model may still be loading; try again, or pick a smaller model."
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return {401: "The server refused the API key. Check or replace it.",
                403: "Access denied: wrong API key, no billing set up, or the server blocks this client.",
                404: "Model or address not found. Pick a model from the list the server reports.",
                429: "Rate limit or quota reached. Wait, add credit, or use a local model."}.get(
            code, f"The server answered HTTP {code}.")
    name = type(exc).__name__
    if name == "LLMEmpty":
        return "The model answered with nothing. Turn thinking off, or use an instruction-tuned chat model."
    if isinstance(exc, ValueError):
        return str(exc)
    return f"{name}: {exc}"


def test_llm(settings: Settings) -> dict:
    from .llm import LLMClient
    if not settings.llm_base_url:
        raise ValueError("no AI server is configured")
    client = LLMClient(settings)
    t = time.time()
    reply = client._chat("Kamu pembawa acara TikTok yang ramah. Jawab dalam satu kalimat pendek bahasa Indonesia.",
                         "Halo! Apa kabar hari ini?", max_tokens=80)
    return {"reply": reply, "seconds": round(time.time() - t, 2), "model": settings.llm_model,
            "endpoint": client.base}


def install_piper_voice(settings: Settings, progress) -> dict:
    """Same download as scripts/get-voices.sh: stream, verify SHA-256, then move into place."""
    dest = Path(settings.piper_model).parent
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / PIPER_VOICE["file"]
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == PIPER_VOICE["sha256"]:
        progress(100, "already installed (checksum matches)")
        return {"path": str(target), "downloaded": False}
    part = target.with_suffix(".part")
    digest = hashlib.sha256()
    with httpx.stream("GET", f"{PIPER_VOICE['base']}/{PIPER_VOICE['file']}", follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with part.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if total:
                    progress(int(done / total * 95), f"downloading {done >> 20} / {total >> 20} MB")
    if digest.hexdigest() != PIPER_VOICE["sha256"]:
        part.unlink(missing_ok=True)
        raise ValueError("checksum mismatch: the download was corrupted, nothing was installed")
    part.replace(target)
    cfg = httpx.get(f"{PIPER_VOICE['base']}/{PIPER_VOICE['file']}.json", follow_redirects=True, timeout=60)
    cfg.raise_for_status()
    target.with_name(target.name + ".json").write_bytes(cfg.content)
    progress(100, "installed and verified")
    return {"path": str(target), "downloaded": True}
