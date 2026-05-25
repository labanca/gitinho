"""Singleton GitHubClient + settings accessor shared by every MCP tool.

We deliberately keep one long-lived `httpx.AsyncClient` per process: the
MCP server runs over stdio and stays up across many tool calls, so reusing
the connection pool matters. A lock guards initialization so the first
two concurrent tool calls don't race to create the client.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from gitinho_mcp.config import Settings, get_settings
from gitinho_mcp.github.client import GitHubClient


@dataclass
class ToolContext:
    settings: Settings
    gh: GitHubClient

    @property
    def org(self) -> str:
        return self.settings.ALLOWED_ORG


_context: ToolContext | None = None
_lock = asyncio.Lock()


async def get_context() -> ToolContext:
    global _context
    if _context is not None:
        return _context
    async with _lock:
        if _context is None:
            settings = get_settings()
            _context = ToolContext(settings=settings, gh=GitHubClient(settings))
    return _context


async def aclose() -> None:
    global _context
    if _context is not None:
        await _context.gh.aclose()
        _context = None
