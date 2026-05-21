"""Agent runner — orchestrates LLM (Azure OpenAI) + tools + streaming."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from openai import AsyncAzureOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import render_system_prompt
from app.agent.tool_registry import build_openai_tools, get_tool
from app.config import Settings
from app.db.models import Export, Message, MessageRole, ToolCall, ToolCallStatus
from app.github.client import GitHubClient, OrgAllowlistError
from app.logging_setup import get_logger
from app.tools._context import ToolContext

log = get_logger(__name__)


@dataclass
class StreamEvent:
    type: str  # token | tool_call | tool_result | export | done | error
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


class AgentRunner:
    def __init__(
        self,
        settings: Settings,
        github_client: GitHubClient,
    ):
        self._settings = settings
        self._gh = github_client
        self._client = AsyncAzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY.get_secret_value(),
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=str(settings.AZURE_OPENAI_ENDPOINT),
        )

    async def run(
        self,
        *,
        db: AsyncSession,
        user_id: UUID,
        user_login: str,
        chat_id: UUID,
        history: list[dict[str, Any]],
        user_message: str,
    ) -> AsyncIterator[StreamEvent]:
        """Yield SSE events as the agent thinks, calls tools, and answers."""
        ctx = ToolContext(
            settings=self._settings,
            gh=self._gh,
            user_id=user_id,
            user_login=user_login,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": render_system_prompt(ctx.org)},
            *history,
            {"role": "user", "content": user_message},
        ]
        tools = build_openai_tools(include_write=False)

        assistant_message = Message(
            id=uuid4(),
            chat_id=chat_id,
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[],
            model=self._settings.AZURE_DEPLOYMENT_ORCHESTRATOR,
        )
        db.add(assistant_message)
        await db.flush()

        full_text_parts: list[str] = []
        recorded_tool_calls: list[dict[str, Any]] = []

        for step in range(self._settings.AGENT_MAX_STEPS):
            stream = await self._client.chat.completions.create(
                model=self._settings.AZURE_DEPLOYMENT_ORCHESTRATOR,
                messages=messages,
                tools=tools,
                stream=True,
                temperature=0.2,
                timeout=self._settings.AGENT_TIMEOUT_S,
            )

            collected: dict[str, Any] = {
                "content": "",
                "tool_calls": {},  # id -> dict
            }

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    collected["content"] += delta.content
                    yield StreamEvent("token", {"text": delta.content})
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        slot = collected["tool_calls"].setdefault(
                            tc.index,
                            {"id": "", "name": "", "arguments": ""},
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments

            # Persist any free-form content delta from this step.
            if collected["content"]:
                full_text_parts.append(collected["content"])

            if not collected["tool_calls"]:
                # No more tool calls; LLM finished.
                break

            # Echo tool-call requests to assistant message + invoke them.
            messages.append(
                {
                    "role": "assistant",
                    "content": collected["content"] or None,
                    "tool_calls": [
                        {
                            "id": v["id"],
                            "type": "function",
                            "function": {"name": v["name"], "arguments": v["arguments"]},
                        }
                        for v in collected["tool_calls"].values()
                    ],
                }
            )

            for call in collected["tool_calls"].values():
                result, status = await self._run_tool(
                    ctx=ctx,
                    db=db,
                    chat_id=chat_id,
                    assistant_message_id=assistant_message.id,
                    user_id=user_id,
                    name=call["name"],
                    raw_args=call["arguments"],
                )
                recorded_tool_calls.append(
                    {
                        "id": call["id"],
                        "name": call["name"],
                        "arguments": call["arguments"],
                        "status": status,
                    }
                )
                yield StreamEvent(
                    "tool_call", {"name": call["name"], "status": status}
                )

                # If the result is an XLSX export, persist it.
                tool_payload: Any = result
                if isinstance(result, dict) and result.get("kind") == "export_xlsx":
                    export_id = await self._save_export(
                        db,
                        user_id=user_id,
                        chat_id=chat_id,
                        filename=result["filename"],
                        payload=result["payload_bytes"],
                    )
                    yield StreamEvent(
                        "export",
                        {
                            "id": str(export_id),
                            "filename": result["filename"],
                            "rows": result.get("rows"),
                        },
                    )
                    tool_payload = {
                        "kind": "export_xlsx",
                        "export_id": str(export_id),
                        "filename": result["filename"],
                        "rows": result.get("rows"),
                    }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": call["name"],
                        "content": json.dumps(
                            tool_payload, ensure_ascii=False, default=str
                        )[:50_000],
                    }
                )

        # Finalize assistant message.
        assistant_message.content = "".join(full_text_parts)
        assistant_message.tool_calls = recorded_tool_calls
        await db.commit()

        yield StreamEvent("done", {"message_id": str(assistant_message.id)})

    async def _run_tool(
        self,
        *,
        ctx: ToolContext,
        db: AsyncSession,
        chat_id: UUID,  # noqa: ARG002
        assistant_message_id: UUID,
        user_id: UUID,
        name: str,
        raw_args: str,
    ) -> tuple[Any, str]:
        spec = get_tool(name)
        started = time.perf_counter()
        if spec is None:
            db.add(
                ToolCall(
                    message_id=assistant_message_id,
                    user_id=user_id,
                    tool_name=name,
                    arguments=None,
                    status=ToolCallStatus.DENIED,
                    duration_ms=0,
                    result_summary="Tool not allowed or unknown",
                )
            )
            await db.commit()
            return {"error": "Tool not allowed", "name": name}, "denied"

        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {}

        try:
            result = await asyncio.wait_for(
                spec.func(ctx=ctx, **args),
                timeout=60,
            )
            status = "ok"
            summary = _truncate(_summarize(result), 1024)
            db.add(
                ToolCall(
                    message_id=assistant_message_id,
                    user_id=user_id,
                    tool_name=name,
                    arguments=args,
                    status=ToolCallStatus.OK,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    result_summary=summary,
                )
            )
            await db.commit()
            return result, status
        except OrgAllowlistError as exc:
            db.add(
                ToolCall(
                    message_id=assistant_message_id,
                    user_id=user_id,
                    tool_name=name,
                    arguments=args,
                    status=ToolCallStatus.DENIED,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    result_summary=str(exc),
                )
            )
            await db.commit()
            return {"error": str(exc)}, "denied"
        except Exception as exc:  # noqa: BLE001
            log.warning("tool.error", tool=name, error=str(exc))
            db.add(
                ToolCall(
                    message_id=assistant_message_id,
                    user_id=user_id,
                    tool_name=name,
                    arguments=args,
                    status=ToolCallStatus.ERROR,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    result_summary=str(exc)[:1024],
                )
            )
            await db.commit()
            return {"error": str(exc)}, "error"

    async def _save_export(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        chat_id: UUID,
        filename: str,
        payload: bytes,
    ) -> UUID:
        from datetime import datetime, timedelta, timezone

        export = Export(
            id=uuid4(),
            user_id=user_id,
            chat_id=chat_id,
            filename=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            payload=payload,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(export)
        await db.flush()
        return export.id


def _summarize(value: Any) -> str:
    if isinstance(value, dict):
        keys = list(value.keys())[:10]
        return f"dict with {len(value)} keys: {keys}"
    if isinstance(value, list):
        return f"list of {len(value)} items"
    return repr(value)[:512]


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."
