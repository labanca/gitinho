"""Download endpoint for generated exports (XLSX)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from app.db.models import Export
from app.deps import DbDep, UserDep

router = APIRouter()


@router.get("/{export_id}")
async def download_export(export_id: UUID, user: UserDep, db: DbDep) -> Response:
    stmt = select(Export).where(Export.id == export_id, Export.user_id == user.id)
    exp = (await db.execute(stmt)).scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=404, detail="Export not found")
    if exp.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Export expired")
    return Response(
        content=exp.payload,
        media_type=exp.mime,
        headers={
            "Content-Disposition": f'attachment; filename="{exp.filename}"',
            "Cache-Control": "no-store",
        },
    )
