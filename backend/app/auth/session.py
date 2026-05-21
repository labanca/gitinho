"""Session management — opaque tokens hashed at rest."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session as SessionModel
from app.db.models import User

SESSION_COOKIE = "gitinho_session"
CSRF_COOKIE = "gitinho_csrf"
SESSION_TTL = timedelta(days=7)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ip_hash(request: Request) -> str | None:
    ip = request.client.host if request.client else None
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]


async def create_session(
    db: AsyncSession,
    *,
    user: User,
    request: Request,
    response: Response,
    is_secure: bool,
) -> SessionModel:
    raw = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    sess = SessionModel(
        user_id=user.id,
        token_hash=_hash(raw),
        expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        ip_hash=_ip_hash(request),
        user_agent=(request.headers.get("user-agent") or "")[:500],
    )
    db.add(sess)
    await db.commit()

    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=False,  # readable by JS for double-submit
        secure=is_secure,
        samesite="lax",
        path="/",
    )
    return sess


async def resolve_session(request: Request, db: AsyncSession) -> User | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    stmt = (
        select(SessionModel, User)
        .join(User, User.id == SessionModel.user_id)
        .where(
            SessionModel.token_hash == _hash(raw),
            SessionModel.revoked_at.is_(None),
            SessionModel.expires_at > datetime.now(timezone.utc),
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    _, user = row
    if not user.is_active:
        return None
    return user


async def revoke_session(db: AsyncSession, request: Request, response: Response) -> None:
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        stmt = select(SessionModel).where(SessionModel.token_hash == _hash(raw))
        sess = (await db.execute(stmt)).scalar_one_or_none()
        if sess is not None:
            sess.revoked_at = datetime.now(timezone.utc)
            await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def verify_csrf(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header:
        return False
    return hmac.compare_digest(cookie, header)


def csrf_required(method: str) -> bool:
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def parse_uuid(s: str) -> UUID | None:
    try:
        return UUID(s)
    except (ValueError, TypeError):
        return None
