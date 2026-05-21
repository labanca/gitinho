"""Context passed to every tool: org, GitHub client, settings, user."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.config import Settings
from app.github.client import GitHubClient


@dataclass
class ToolContext:
    settings: Settings
    gh: GitHubClient
    user_id: UUID
    user_login: str

    @property
    def org(self) -> str:
        return self.settings.ALLOWED_ORG
