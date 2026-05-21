"""Client for the official GitHub MCP server.

The GitHub MCP server (https://github.com/github/github-mcp-server) is a
go binary that we run as a subprocess and communicate with via stdio. It
exposes a large set of read-only tools (and write tools we filter out).

In fase 1, we use it as a *fallback* for queries the LLM wants that
aren't covered by our custom tools. Custom tools take precedence because
they are precision-engineered with GraphQL.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]


class GitHubMCPClient:
    """Async client wrapping the `mcp` python SDK stdio transport.

    Lazy import keeps the module loadable in environments without the
    MCP server installed.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._stack: AsyncExitStack | None = None
        self._session: Any = None
        self._tools: list[McpTool] = []
        self._lock = asyncio.Lock()

    async def start(self, github_token: str) -> None:
        if not self._settings.MCP_GITHUB_ENABLED:
            log.info("mcp.disabled")
            return
        async with self._lock:
            if self._session is not None:
                return
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client
            except ImportError:
                log.warning("mcp.sdk_missing — MCP disabled")
                return

            stack = AsyncExitStack()
            params = StdioServerParameters(
                command=self._settings.MCP_GITHUB_COMMAND,
                args=self._settings.MCP_GITHUB_ARGS.split(),
                env={
                    "GITHUB_PERSONAL_ACCESS_TOKEN": github_token,
                    "GITHUB_TOOLSETS": "repos,issues,pull_requests,users,context",
                    "GITHUB_READ_ONLY": "1",
                },
            )
            try:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                listed = await session.list_tools()
                self._tools = [
                    McpTool(
                        name=t.name,
                        description=t.description or "",
                        input_schema=t.inputSchema or {},
                    )
                    for t in listed.tools
                    if self._is_read_only(t.name)
                ]
                self._session = session
                self._stack = stack
                log.info("mcp.connected", tools=len(self._tools))
            except Exception as exc:  # noqa: BLE001
                log.warning("mcp.start_failed", error=str(exc))
                await stack.aclose()

    @staticmethod
    def _is_read_only(name: str) -> bool:
        write_prefixes = (
            "create_", "update_", "delete_", "merge_", "close_",
            "open_", "fork_", "add_", "remove_", "set_", "transfer_",
            "dispatch_", "rerun_", "cancel_", "approve_", "request_",
        )
        return not any(name.startswith(p) for p in write_prefixes)

    @property
    def tools(self) -> list[McpTool]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise RuntimeError("MCP client not started")
        if not self._is_read_only(name):
            raise PermissionError(f"Tool '{name}' is not read-only")
        result = await self._session.call_tool(name, arguments)
        return result

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None
            self._tools = []
