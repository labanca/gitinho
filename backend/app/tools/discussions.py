"""Discussions tooling (counts and recent items via GraphQL)."""

from __future__ import annotations

from typing import Any

from app.tools._base import ToolMode, registry
from app.tools._context import ToolContext

ORG_DISCUSSIONS = """
query OrgDiscussions($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        discussions(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
          totalCount
          nodes { title url createdAt author { login } }
        }
      }
    }
  }
}
"""


@registry.register(mode=ToolMode.READ)
async def discussions_overview(ctx: ToolContext) -> dict[str, Any]:
    """Per-repo discussion totals and the most recent discussion (if any)."""
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
    return {"org": ctx.org, "total_discussions": grand, "per_repo": out}
