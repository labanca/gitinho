"""Dependency injection helpers for FastAPI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_db():
        yield session


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
DbDep = Annotated[AsyncSession, Depends(db_session)]


async def require_user(request: Request, db: DbDep) -> "User":  # type: ignore[name-defined]
    """Resolve the current user from the session cookie. Raises 401 otherwise."""
    from app.auth.session import resolve_session

    user = await resolve_session(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return user


UserDep = Annotated["User", Depends(require_user)]  # noqa: F821
