"""Settings loaded from environment variables.

Secrets (private keys) are read on demand from the path on disk. The
Settings instance itself never holds the PEM contents.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ALLOWED_ORG: str = Field(default="splor-mg", min_length=1, max_length=80)
    GH_APP_ID: int = Field(..., description="GitHub App numeric ID")
    GH_APP_INSTALLATION_ID: int = Field(..., description="Installation ID in the org")
    GH_APP_PRIVATE_KEY_PATH: Path = Field(..., description="Path to .pem private key")
    GLOSSARY_CACHE_TTL_S: int = 300
    GITHUB_API_BASE: str = "https://api.github.com"
    GITHUB_GRAPHQL_URL: str = "https://api.github.com/graphql"
    DOCUMENT_INGEST_MAX_MB: int = 25

    @field_validator("ALLOWED_ORG")
    @classmethod
    def _org_slug(cls, v: str) -> str:
        if not v.replace("-", "").isalnum():
            raise ValueError("ALLOWED_ORG must be a valid GitHub login")
        return v.lower()

    def gh_app_private_key(self) -> str:
        """Read the GitHub App private key from disk on each call.

        Kept off the Settings instance so the PEM never lives in process
        memory longer than necessary and never lands in repr/logs.
        """
        return self.GH_APP_PRIVATE_KEY_PATH.read_text(encoding="utf-8")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
