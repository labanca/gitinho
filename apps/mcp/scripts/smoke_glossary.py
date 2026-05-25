"""Smoke test for the glossary MCP tool."""

from __future__ import annotations

import asyncio
import json

from gitinho_mcp import tools  # noqa: F401
from gitinho_mcp.tools._context import aclose
from gitinho_mcp.tools.glossary import get_org_glossary


async def main() -> None:
    try:
        result = await get_org_glossary()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await aclose()


if __name__ == "__main__":
    asyncio.run(main())
