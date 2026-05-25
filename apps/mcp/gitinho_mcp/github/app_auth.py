"""GitHub App authentication: short-lived JWT + cached installation token."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import jwt

from gitinho_mcp.config import Settings


_INSTALLATION_TOKEN_URL = (
    "https://api.github.com/app/installations/{installation_id}/access_tokens"
)


@dataclass
class InstallationToken:
    token: str
    expires_at: datetime  # UTC

    def is_expired(self, leeway_s: int = 30) -> bool:
        return time.time() + leeway_s >= self.expires_at.timestamp()


class GitHubAppAuth:
    """Issues App JWTs and caches the installation access token until expiry."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: InstallationToken | None = None

    def _build_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 9 * 60,  # max 10 min per GitHub docs
            "iss": str(self._settings.GH_APP_ID),
        }
        return jwt.encode(
            payload,
            self._settings.gh_app_private_key(),
            algorithm="RS256",
        )

    async def installation_token(self) -> str:
        if self._token is not None and not self._token.is_expired():
            return self._token.token
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _INSTALLATION_TOKEN_URL.format(
                    installation_id=self._settings.GH_APP_INSTALLATION_ID
                ),
                headers={
                    "Authorization": f"Bearer {self._build_jwt()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        resp.raise_for_status()
        data = resp.json()
        expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        self._token = InstallationToken(token=data["token"], expires_at=expires)
        return self._token.token
