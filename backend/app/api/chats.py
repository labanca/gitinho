"""Chat CRUD endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.session import csrf_required, verify_csrf
from app.db.models import Chat, Message
from app.deps import DbDep, SettingsDep, UserDep

router = APIRouter()


class ChatOut(BaseModel):
    id: UUID
    title: str
    org: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    class Config:
        from_attributes = True


class ChatCreate(BaseModel):
    title: str = Field(default="Nova conversa", max_length=200)


class ChatPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


def _csrf_guard(request: Request) -> None:
    if csrf_required(request.method) and not verify_csrf(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")


@router.get("", response_model=list[ChatOut])
async def list_chats(user: UserDep, db: DbDep) -> list[Chat]:
    stmt = (
        select(Chat)
        .where(Chat.user_id == user.id)
        .order_by(Chat.updated_at.desc())
        .limit(200)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=ChatOut, status_code=201)
async def create_chat(
    request: Request,
    user: UserDep,
    db: DbDep,
    settings: SettingsDep,
    body: ChatCreate,
) -> Chat:
    _csrf_guard(request)
    chat = Chat(user_id=user.id, title=body.title, org=settings.ALLOWED_ORG)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


@router.get("/{chat_id}", response_model=ChatOut)
async def get_chat(chat_id: UUID, user: UserDep, db: DbDep) -> Chat:
    chat = await _own_chat(chat_id, user, db)
    return chat


@router.patch("/{chat_id}", response_model=ChatOut)
async def patch_chat(
    request: Request,
    chat_id: UUID,
    user: UserDep,
    db: DbDep,
    body: ChatPatch,
) -> Chat:
    _csrf_guard(request)
    chat = await _own_chat(chat_id, user, db)
    if body.title is not None:
        chat.title = body.title
    if body.archived is not None:
        chat.archived_at = datetime.now(timezone.utc) if body.archived else None
    await db.commit()
    await db.refresh(chat)
    return chat


@router.get("/{chat_id}/messages")
async def list_messages(chat_id: UUID, user: UserDep, db: DbDep) -> list[dict]:
    await _own_chat(chat_id, user, db)
    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(m.id),
            "role": m.role.value,
            "content": m.content,
            "tool_calls": m.tool_calls or [],
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


async def _own_chat(chat_id: UUID, user, db) -> Chat:
    chat = (
        await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    ).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat
