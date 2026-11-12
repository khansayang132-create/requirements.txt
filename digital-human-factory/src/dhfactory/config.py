"""Settings from the environment / .env. Secrets are SecretStr and never printed."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDER_ENV = {
    "heygen": "HEYGEN_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "runway": "RUNWAYML_API_SECRET",
    "did": "DID_API_KEY",
    "synthesia": "SYNTHESIA_API_KEY",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    heygen_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    runwayml_api_secret: SecretStr | None = None
    did_api_key: SecretStr | None = None
    synthesia_api_key: SecretStr | None = None
    dhf_max_spend_usd: float = 5.0
    dhf_workspace: Path = Path(".")
    http_timeout: float = 60.0

    def key(self, provider: str) -> str | None:
        v = getattr(self, PROVIDER_ENV[provider].lower(), None)
        return v.get_secret_value() if v else None

    @property
    def root(self) -> Path:
        return self.dhf_workspace.resolve()
