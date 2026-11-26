"""Runtime settings. Everything is read from the environment so the same code runs on a laptop,
a server or a phone. Nothing here is a secret; the encryption key lives in its own file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: _env_path("NOVA_DATA_DIR", Path.home() / ".nova"))
    # Optional bearer token. When set, every /api route except /api/health requires it.
    api_key: str = field(default_factory=lambda: os.environ.get("NOVA_API_KEY", ""))
    # Optional engines: a model only counts as available when its file exists.
    # Default: the Indonesian voice that scripts/get-voices.sh installs, if it is there.
    piper_model: str = field(default_factory=lambda: os.environ.get("NOVA_PIPER_MODEL") or str(
        Path(os.environ.get("NOVA_MODELS_DIR", Path.home() / ".nova" / "models")) / "id_ID-news_tts-medium.onnx"))
    # Neural Indonesian voice cloning (requirements-neural.txt, ~3 GB download on first use).
    chatterbox: bool = field(default_factory=lambda: os.environ.get("NOVA_CHATTERBOX", "") == "1")
    sherpa_model_dir: str = field(default_factory=lambda: os.environ.get("NOVA_SHERPA_MODEL_DIR", ""))
    # Optional LLM: any OpenAI-compatible endpoint (llama.cpp server with a GGUF model, Ollama, OmniRoute).
    llm_base_url: str = field(default_factory=lambda: os.environ.get("NOVA_LLM_BASE_URL", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("NOVA_LLM_MODEL", "local"))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("NOVA_LLM_API_KEY", "none"))
    # Off by default: reasoning adds seconds and can eat the whole reply budget.
    llm_thinking: bool = field(default_factory=lambda: os.environ.get("NOVA_LLM_THINKING", "") == "1")
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("NOVA_MAX_UPLOAD_MB", "50")))

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def key_file(self) -> Path:
        return self.data_dir / "secret.key"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.profiles_dir, self.projects_dir, self.outputs_dir):
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
