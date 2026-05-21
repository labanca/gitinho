"""Pull-request counts and search."""

from __future__ import annotations

from typing import Any

from app.github.graphql import ORG_OPEN_PRS
from app.tools._base import ToolMode, registry
from app.tools._context import ToolContext


@registry.register(mode=ToolMode.READ)
async def count_open_prs(
    ctx: ToolContext,
    repo: str | None = None,
) -> dict[str, Any]:
    """Count open PRs across the org, or for a single repo if `repo` given.

    Uses GraphQL totalCount — exact, not approximate.
    """
    if repo:
        res = await ctx.gh.get(
            "/search/issues",
            params={"q": f"is:pr is:open repo:{ctx.org}/{repo}", "per_page": 1},
            owner=ctx.org,
        )
        return {"repo": f"{ctx.org}/{repo}", "open_prs": (res or {}).get("total_count", 0)}

    total = 0
    cursor: str | None = None
    per_repo: list[dict[str, int]] = []
    while True:
        data = await ctx.gh.graphql(ORG_OPEN_PRS, {"org": ctx.org, "after": cursor})
        page = data["organization"]["repositories"]
        for n in page["nodes"]:
            c = n["pullRequests"]["totalCount"]
            if c > 0:
                per_repo.append({"repo": n["name"], "open_prs": c})
            total += c
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    per_repo.sort(key=lambda x: -x["open_prs"])
    return {"org": ctx.org, "total_open_prs": total, "per_repo": per_repo}


@registry.register(mode=ToolMode.READ)
async def last_pr_by_user(ctx: ToolContext, login: str) -> dict[str, Any]:
    """Most recent pull request created by a user in the org."""
    q = f"is:pr author:{login} org:{ctx.org} sort:created-desc"
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
        "state": it["state"],
        "created_at": it["created_at"],
        "repo": it["repository_url"].split("/repos/")[-1],
        "number": it["number"],
    }
