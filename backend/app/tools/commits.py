"""Commit lookups (latest by user / by repo)."""

from __future__ import annotations

from typing import Any

from app.github.graphql import REPO_LAST_COMMIT
from app.tools._base import ToolMode, registry
from app.tools._context import ToolContext


@registry.register(mode=ToolMode.READ)
async def last_commit_in_repo(ctx: ToolContext, repo: str) -> dict[str, Any]:
    """Most recent commit on the default branch of a repo."""
    data = await ctx.gh.graphql(REPO_LAST_COMMIT, {"org": ctx.org, "repo": repo})
    r = data.get("repository") or {}
    if not r:
        return {"repo": f"{ctx.org}/{repo}", "found": False}
    branch_ref = r.get("defaultBranchRef") or {}
    target = branch_ref.get("target") or {}
    if not target:
        return {"repo": f"{ctx.org}/{repo}", "found": False}
    return {
        "repo": f"{ctx.org}/{repo}",
        "branch": branch_ref.get("name"),
        "sha": target.get("oid"),
        "message": target.get("messageHeadline"),
        "committed_at": target.get("committedDate"),
        "url": target.get("url"),
        "author": {
            "login": (target.get("author") or {}).get("user", {}).get("login")
            if target.get("author")
            else None,
            "name": (target.get("author") or {}).get("name"),
        },
        "found": True,
    }


@registry.register(mode=ToolMode.READ)
async def last_commit_by_user(
    ctx: ToolContext,
    login: str,
    repo: str | None = None,
) -> dict[str, Any]:
    """Most recent commit authored by `login` in the org (optionally in `repo`).

    Uses /search/commits which supports author:<login> + org/repo scoping.
    """
    parts = [f"author:{login}"]
    parts.append(f"repo:{ctx.org}/{repo}" if repo else f"org:{ctx.org}")
    q = " ".join(parts)
    res = await ctx.gh.get(
        "/search/commits",
        params={"q": q, "sort": "committer-date", "order": "desc", "per_page": 1},
        owner=ctx.org,
    )
    items = (res or {}).get("items", []) if isinstance(res, dict) else []
    if not items:
        return {"login": login, "repo": repo, "found": False}
    c = items[0]
    return {
        "login": login,
        "repo": c["repository"]["full_name"],
        "sha": c["sha"],
        "message": c["commit"]["message"].splitlines()[0],
        "committed_at": c["commit"]["committer"]["date"],
        "url": c["html_url"],
        "found": True,
    }
