"""Issues — counts and last-by-user."""

from __future__ import annotations

from typing import Any

from app.github.graphql import ORG_OPEN_ISSUES
from app.tools._base import ToolMode, registry
from app.tools._context import ToolContext


@registry.register(mode=ToolMode.READ)
async def count_open_issues(
    ctx: ToolContext,
    repo: str | None = None,
) -> dict[str, Any]:
    """Count open issues across the org, or for a single repo if `repo` given."""
    if repo:
        data = await ctx.gh.get(
            f"/repos/{ctx.org}/{repo}",
            owner=ctx.org,
        )
        return {"repo": f"{ctx.org}/{repo}", "open_issues": data.get("open_issues_count", 0)}

    total = 0
    cursor: str | None = None
    per_repo: list[dict[str, int]] = []
    while True:
        data = await ctx.gh.graphql(ORG_OPEN_ISSUES, {"org": ctx.org, "after": cursor})
        page = data["organization"]["repositories"]
        for n in page["nodes"]:
            c = n["issues"]["totalCount"]
            if c > 0:
                per_repo.append({"repo": n["name"], "open_issues": c})
            total += c
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    per_repo.sort(key=lambda x: -x["open_issues"])
    return {"org": ctx.org, "total_open_issues": total, "per_repo": per_repo}


@registry.register(mode=ToolMode.READ)
async def last_issue_by_user(ctx: ToolContext, login: str) -> dict[str, Any]:
    """Most recent issue created by a user in the org."""
    q = f"is:issue author:{login} org:{ctx.org} sort:created-desc"
    res = await ctx.gh.get(
        "/search/issues",
        params={"q": q, "per_page": 1},
        owner=ctx.org,
    )
    items = (res or {}).get("items", []) if isinstance(res, dict) else []
    if not items:
        return {"login": login, "found": False}
    it = items[0]
    return {
        "login": login,
        "found": True,
        "title": it["title"],
        "url": it["html_url"],
        "created_at": it["created_at"],
        "repo": it["repository_url"].split("/repos/")[-1],
        "number": it["number"],
    }


@registry.register(mode=ToolMode.READ)
async def search_issues(
    ctx: ToolContext,
    query: str,
    limit: int = 30,
) -> dict[str, Any]:
    """Search issues with a free-form GitHub query (scoped to the org)."""
    limit = max(1, min(100, int(limit)))
    safe = f"({query}) org:{ctx.org}"
    res = await ctx.gh.get(
        "/search/issues",
        params={"q": safe, "per_page": limit},
        owner=ctx.org,
    )
    items = (res or {}).get("items", []) if isinstance(res, dict) else []
    total = (res or {}).get("total_count", 0) if isinstance(res, dict) else 0
    return {
        "query": safe,
        "total": total,
        "items": [
            {
                "title": i["title"],
                "url": i["html_url"],
                "state": i["state"],
                "created_at": i["created_at"],
                "user": i["user"]["login"],
                "repo": i["repository_url"].split("/repos/")[-1],
            }
            for i in items
        ],
    }
