"""Org glossary tool — fetches `<org>/.github/gitinho-context.md`.

The glossary is owner-curated context (acronyms, domain conventions,
project codenames) that the LLM should use to interpret terms specific
to the organization. Cached in-process for `GLOSSARY_CACHE_TTL_S` so
chat sessions don't spam the contents endpoint.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import get_context

_GLOSSARY_REPO = ".github"
_GLOSSARY_PATH = "gitinho-context.md"

_cache: dict[str, tuple[float, str | None]] = {}


@mcp.tool()
async def get_org_glossary() -> dict[str, Any]:
    """Fetch the organization's glossary (`.github/gitinho-context.md`).

    Returns the markdown body when present. Call this tool when you
    encounter an unfamiliar org-specific term (codename, acronym,
    convention) before answering, so the response uses the right
    definitions. Absent file is a normal case — the org may not have
    one yet.

    Cached in-memory for `GLOSSARY_CACHE_TTL_S` seconds (default 5 min).
    """
    ctx = await get_context()
    org = ctx.org
    ttl = ctx.settings.GLOSSARY_CACHE_TTL_S
    now = time.time()
    cached = _cache.get(org)
    if cached and now - cached[0] < ttl:
        return _format(org, cached[1])

    content: str | None = None
    try:
        data = await ctx.gh.get(
            f"/repos/{org}/{_GLOSSARY_REPO}/contents/{_GLOSSARY_PATH}",
            owner=org,
        )
        if isinstance(data, dict) and data.get("encoding") == "base64":
            raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            content = raw.strip() or None
    except httpx.HTTPStatusError as exc:
        # 404 is normal (no glossary yet). Anything else is logged at the
        # MCP server level via httpx — we don't need to re-raise.
        if exc.response.status_code != 404:
            raise

    _cache[org] = (now, content)
    return _format(org, content)


def _format(org: str, content: str | None) -> dict[str, Any]:
    return {
        "org": org,
        "path": f"{org}/{_GLOSSARY_REPO}/{_GLOSSARY_PATH}",
        "found": content is not None,
        "content": content,
    }
