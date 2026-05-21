"""GitHub OAuth flow.

We use OAuth only for *identity* + org membership check. The user's OAuth
token is discarded after the membership check — we never store it. Org
data is fetched server-side using the GitHub App credentials.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AuditLog, User

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


def state_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        settings.SESSION_SECRET.get_secret_value(), salt="oauth-state"
    )


def build_authorize_url(settings: Settings) -> tuple[str, str]:
    state = secrets.token_urlsafe(24)
    signed = state_serializer(settings).dumps(state)
    qs = urlencode(
        {
            "client_id": settings.OAUTH_CLIENT_ID,
            "redirect_uri": str(settings.OAUTH_REDIRECT_URI),
            "scope": "read:org user:email",
            "state": signed,
            "allow_signup": "false",
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{qs}", signed


def verify_state(settings: Settings, signed: str) -> bool:
    try:
        state_serializer(settings).loads(signed, max_age=600)
        return True
    except BadSignature:
        return False


async def exchange_code_for_token(settings: Settings, code: str) -> str | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.OAUTH_CLIENT_ID,
                "client_secret": settings.OAUTH_CLIENT_SECRET.get_secret_value(),
                "code": code,
                "redirect_uri": str(settings.OAUTH_REDIRECT_URI),
            },
        )
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


async def fetch_github_user(token: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code != 200:
        return None
    return resp.json()


async def upsert_user(db: AsyncSession, payload: dict) -> User:
    stmt = select(User).where(User.github_id == payload["id"])
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        user = User(
            github_id=payload["id"],
            github_login=payload["login"],
            email=payload.get("email"),
            avatar_url=payload.get("avatar_url"),
            is_active=True,
        )
        db.add(user)
    else:
        user.github_login = payload["login"]
        user.email = payload.get("email") or user.email
        user.avatar_url = payload.get("avatar_url") or user.avatar_url
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    return user


async def record_audit(db: AsyncSession, event: str, detail: dict | None = None) -> None:
    db.add(AuditLog(event=event, detail=detail))
    await db.commit()
