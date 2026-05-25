"""Helper: list every tool registered on the gitinho MCP server.

Used to verify all @mcp.tool()-decorated functions get picked up via the
package's __init__.py import chain.
"""

from __future__ import annotations

import asyncio

from gitinho_mcp import tools  # noqa: F401 — triggers @mcp.tool() registrations
from gitinho_mcp.server import mcp


async def main() -> None:
    tlist = await mcp.list_tools()
    print(f"Total tools: {len(tlist)}")
    for t in sorted(tlist, key=lambda x: x.name):
        print(f"  - {t.name}")


if __name__ == "__main__":
    asyncio.run(main())
