"""Application settings loaded from environment.

Never log values from this module directly — secrets are excluded from
repr() and JSON encoding for safety.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "production", "test"] = "development"
    APP_BASE_URL: AnyHttpUrl = Field(default="http://localhost:8000")
    SESSION_SECRET: SecretStr
    MAINTENANCE_MODE: bool = False

    # ── Organização alvo ────────────────────────────────────────────
    ALLOWED_ORG: str = Field(min_length=1, max_length=80)

    # ── GitHub OAuth (login dos usuários) ───────────────────────────
    OAUTH_CLIENT_ID: str
    OAUTH_CLIENT_SECRET: SecretStr
    OAUTH_REDIRECT_URI: AnyHttpUrl

    # ── GitHub App (acesso aos dados da org) ────────────────────────
    GH_APP_ID: int
    GH_APP_INSTALLATION_ID: int
    GH_APP_PRIVATE_KEY_PATH: Path | None = None
    GH_APP_PRIVATE_KEY: SecretStr | None = None

    # ── Azure OpenAI / Foundry ──────────────────────────────────────
    AZURE_OPENAI_ENDPOINT: AnyHttpUrl
    AZURE_OPENAI_API_KEY: SecretStr
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    AZURE_DEPLOYMENT_ORCHESTRATOR: str = "gpt-4.1"
    AZURE_DEPLOYMENT_ANALYTIC: str = "o3"
    AZURE_DEPLOYMENT_LIGHT: str = "gpt-4.1-mini"

    # ── Database ────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://gitinho:gitinho@localhost:5432/gitinho"
    )

    # ── Agente ──────────────────────────────────────────────────────
    AGENT_ALLOW_WRITE: bool = False  # Fase 1: sempre False.
    AGENT_MAX_STEPS: int = 12
    AGENT_TIMEOUT_S: int = 120

    # ── Rate-limit ──────────────────────────────────────────────────
    RATE_LIMIT_USER_PER_MIN: int = 60
    RATE_LIMIT_IP_PER_MIN: int = 20

    # ── MCP ─────────────────────────────────────────────────────────
    MCP_GITHUB_ENABLED: bool = True
    MCP_GITHUB_COMMAND: str = "github-mcp-server"
    MCP_GITHUB_ARGS: str = "stdio"  # space-separated

    # ── Logs ────────────────────────────────────────────────────────
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"

    @field_validator("ALLOWED_ORG")
    @classmethod
    def _org_slug(cls, v: str) -> str:
        # GitHub login: alphanumeric or hyphens, no leading/trailing hyphen.
        if not v.replace("-", "").isalnum():
            raise ValueError("ALLOWED_ORG must be a valid GitHub login")
        return v.lower()

    def gh_app_private_key(self) -> str:
        """Read the GitHub App private key from path or env var."""
        if self.GH_APP_PRIVATE_KEY is not None:
            return self.GH_APP_PRIVATE_KEY.get_secret_value()
        if self.GH_APP_PRIVATE_KEY_PATH is not None:
            return self.GH_APP_PRIVATE_KEY_PATH.read_text(encoding="utf-8")
        raise RuntimeError(
            "GitHub App private key not configured "
            "(set GH_APP_PRIVATE_KEY or GH_APP_PRIVATE_KEY_PATH)"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
