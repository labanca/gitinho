"""Discussions tooling (counts and recent items via GraphQL)."""

from __future__ import annotations

from typing import Any

from gitinho_mcp.github.graphql import ORG_DISCUSSIONS
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import get_context


@mcp.tool()
async def discussions_overview() -> dict[str, Any]:
    """Per-repo discussion totals and the most recent discussion (if any)."""
    ctx = await get_context()
    cursor: str | None = None
    out: list[dict[str, Any]] = []
    grand = 0
    while True:
        data = await ctx.gh.graphql(ORG_DISCUSSIONS, {"org": ctx.org, "after": cursor})
        page = data["organization"]["repositories"]
        for n in page["nodes"]:
            d = n["discussions"]
            grand += d["totalCount"]
            if d["totalCount"] > 0:
                last = d["nodes"][0] if d["nodes"] else None
                out.append(
                    {
                        "repo": n["name"],
                        "total": d["totalCount"],
                        "last": last
                        and {
                            "title": last["title"],
                            "url": last["url"],
                            "created_at": last["createdAt"],
                            "author": (last["author"] or {}).get("login"),
                        },
                    }
                )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    out.sort(key=lambda x: -x["total"])
    return {
        "org": ctx.org,
        "total_discussions": grand,
        "per_repo": out,
        "_chat_table": {
            "title": f"Discussões por repositório — {ctx.org}",
            "description": f"{grand} discussões em {len(out)} repositórios",
            "data_field": "per_repo",
            "columns": [
                {"key": "repo", "label": "Repositório", "type": "string"},
                {"key": "total", "label": "Total", "type": "number"},
            ],
        },
    }
