"""SSE stream — runs the agent for the latest user message in a chat."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.agent.runner import AgentRunner
from app.db.models import Chat, Message, MessageRole
from app.deps import DbDep, SettingsDep, UserDep
from app.github.client import GitHubClient

router = APIRouter()


@router.get("/{chat_id}/stream")
async def stream_response(
    chat_id: UUID,
    user: UserDep,
    db: DbDep,
    settings: SettingsDep,
):
    chat = (
        await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    ).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Load history (excluding the very last user message — agent receives it explicitly).
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.chat_id == chat.id)
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not rows or rows[-1].role != MessageRole.USER:
        raise HTTPException(status_code=400, detail="No pending user message")

    last_user = rows[-1]
    history = [
        {"role": m.role.value, "content": m.content or ""}
        for m in rows[:-1]
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content
    ]

    gh = GitHubClient(settings)
    runner = AgentRunner(settings, gh)

    async def event_gen():
        try:
            async for ev in runner.run(
                db=db,
                user_id=user.id,
                user_login=user.github_login,
                chat_id=chat.id,
                history=history,
                user_message=last_user.content,
            ):
                yield {"event": ev.type, "data": _to_json(ev.data)}
        except Exception as exc:  # noqa: BLE001
            yield {"event": "error", "data": _to_json({"message": str(exc)})}
        finally:
            await gh.aclose()

    return EventSourceResponse(event_gen())


def _to_json(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, default=str)
