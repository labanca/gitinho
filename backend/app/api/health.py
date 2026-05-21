"""Health endpoints (liveness / readiness)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.deps import DbDep

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(db: DbDep) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ready"}
