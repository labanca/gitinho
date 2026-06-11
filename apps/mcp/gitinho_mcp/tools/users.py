"""User-level tools (list members, count contributions)."""

from __future__ import annotations

from typing import Any

from gitinho_mcp.github.graphql import ORG_MEMBERS
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import get_context


@mcp.tool()
async def list_org_members() -> dict[str, Any]:
    """List all members of the configured organization."""
    ctx = await get_context()
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        data = await ctx.gh.graphql(ORG_MEMBERS, {"org": ctx.org, "after": cursor})
        page = data["organization"]["membersWithRole"]
        for n in page["nodes"]:
            out.append(
                {"login": n["login"], "name": n.get("name"), "avatar_url": n["avatarUrl"]}
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return {
        "org": ctx.org,
        "total": len(out),
        "members": out,
        "_chat_table": {
            "title": f"Membros da organização {ctx.org}",
            "description": f"{len(out)} membros",
            "data_field": "members",
            "columns": [
                {"key": "login", "label": "Login", "type": "string"},
                {"key": "name", "label": "Nome", "type": "string"},
                {"key": "avatar_url", "label": "Avatar", "type": "string"},
            ],
        },
    }


@mcp.tool()
async def count_user_contributions(
    login: str,
    type: str = "issue",
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Count a user's contributions of a given type in the org.

    `type`: one of 'issue', 'pr', 'pr-review', 'commit'.
    `since` / `until`: ISO dates (YYYY-MM-DD) or omitted.
    """
    ctx = await get_context()
    parts: list[str] = [f"org:{ctx.org}", f"author:{login}"]
    if type == "issue":
        parts.append("is:issue")
        path = "/search/issues"
    elif type == "pr":
        parts.append("is:pr")
        path = "/search/issues"
    elif type == "pr-review":
        parts = [f"org:{ctx.org}", f"reviewed-by:{login}", "is:pr"]
        path = "/search/issues"
    elif type == "commit":
        parts = [f"org:{ctx.org}", f"author:{login}"]
        path = "/search/commits"
    else:
        raise ValueError(f"Unknown type: {type}")

    if since:
        parts.append(f"created:>={since}")
    if until:
        parts.append(f"created:<={until}")
    q = " ".join(parts)
    res = await ctx.gh.get(path, params={"q": q, "per_page": 1}, owner=ctx.org)
    total = (res or {}).get("total_count", 0) if isinstance(res, dict) else 0
    return {"login": login, "type": type, "since": since, "until": until, "count": total}
