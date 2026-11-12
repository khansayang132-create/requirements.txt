from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

KEYS = {"runway": "RUNWAYML_API_SECRET", "flux": "BFL_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY", "kling_access": "KLING_ACCESS_KEY",
        "kling_secret": "KLING_SECRET_KEY", "higgsfield": "HF_KEY", "comfyui": "COMFY_API_KEY"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    runwayml_api_secret: SecretStr | None = None
    bfl_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    kling_access_key: SecretStr | None = None
    kling_secret_key: SecretStr | None = None
    hf_key: SecretStr | None = Field(None, validation_alias=AliasChoices("HF_KEY", "HIGGSFIELD_API_KEY"))
    hf_api_key: SecretStr | None = None
    hf_api_secret: SecretStr | None = None
    comfy_api_key: SecretStr | None = None
    comfy_base_url: str | None = None
    kling_api_key: SecretStr | None = None      # v0.3 name; Kling's API needs the access + secret key pair instead
    comfyui_base_url: str | None = None         # v0.3 name: a local ComfyUI server (not driven yet, see provider-matrix)
    cs_max_spend_usd: float = 5.0
    cs_workspace: Path = Path(".")
    http_timeout: float = 60.0

    def secret(self, field: str) -> str | None:
        v = getattr(self, field, None)
        return v.get_secret_value() if v else None

    @property
    def root(self) -> Path:
        return self.cs_workspace.resolve()
