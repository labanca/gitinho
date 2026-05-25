"""Smoke test for the convert_document MCP tool."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

from gitinho_mcp import tools  # noqa: F401
from gitinho_mcp.tools._context import aclose
from gitinho_mcp.tools.documents import convert_document


async def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m apps.mcp.scripts.smoke_documents <file>")
        sys.exit(2)
    path = Path(sys.argv[1])
    content_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    try:
        result = await convert_document(content_base64=content_b64, filename=path.name)
        result_view = dict(result)
        md = result_view.get("markdown")
        if isinstance(md, str) and len(md) > 800:
            result_view["markdown"] = md[:800] + f"... <{len(md) - 800} more chars>"
        print(json.dumps(result_view, indent=2, ensure_ascii=False))
    finally:
        await aclose()


if __name__ == "__main__":
    asyncio.run(main())
