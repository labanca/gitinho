"""Endpoints to post a user message into a chat."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.session import csrf_required, verify_csrf
from app.db.models import Chat, Message, MessageRole
from app.deps import DbDep, UserDep

router = APIRouter()


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


@router.post("/{chat_id}/messages", status_code=201)
async def post_message(
    request: Request,
    chat_id: UUID,
    user: UserDep,
    db: DbDep,
    body: MessageIn,
) -> dict:
    if csrf_required(request.method) and not verify_csrf(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")

    chat = (
        await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    ).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    msg = Message(
        chat_id=chat.id,
        role=MessageRole.USER,
        content=body.content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return {"id": str(msg.id), "created_at": msg.created_at.isoformat()}
