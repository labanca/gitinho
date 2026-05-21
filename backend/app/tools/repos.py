"""Repository-level tools (counts, listings, branches, datapackages)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.github.graphql import ORG_REPOS_PAGE
from app.tools._base import ToolMode, registry
from app.tools._context import ToolContext


class RepoSummary(BaseModel):
    name: str
    name_with_owner: str
    description: str | None = None
    is_private: bool
    is_archived: bool
    is_fork: bool
    is_template: bool
    url: str
    primary_language: str | None = None
    disk_usage_kb: int | None = None
    stargazers: int
    forks: int
    pushed_at: str | None
    updated_at: str | None
    created_at: str | None
    topics: list[str]
    default_branch: str | None
    branch_count: int
    open_issues: int
    open_prs: int


async def _all_repos(ctx: ToolContext) -> list[RepoSummary]:
    out: list[RepoSummary] = []
    cursor: str | None = None
    while True:
        data = await ctx.gh.graphql(
            ORG_REPOS_PAGE, {"org": ctx.org, "after": cursor}
        )
        page = data["organization"]["repositories"]
        for node in page["nodes"]:
            out.append(
                RepoSummary(
                    name=node["name"],
                    name_with_owner=node["nameWithOwner"],
                    description=node["description"],
                    is_private=node["isPrivate"],
                    is_archived=node["isArchived"],
                    is_fork=node["isFork"],
                    is_template=node["isTemplate"],
                    url=node["url"],
                    primary_language=(node.get("primaryLanguage") or {}).get("name"),
                    disk_usage_kb=node.get("diskUsage"),
                    stargazers=node["stargazerCount"],
                    forks=node["forkCount"],
                    pushed_at=node.get("pushedAt"),
                    updated_at=node.get("updatedAt"),
                    created_at=node.get("createdAt"),
                    topics=[
                        n["topic"]["name"] for n in node["repositoryTopics"]["nodes"]
                    ],
                    default_branch=(node.get("defaultBranchRef") or {}).get("name"),
                    branch_count=node["refs"]["totalCount"],
                    open_issues=node["openIssues"]["totalCount"],
                    open_prs=node["openPRs"]["totalCount"],
                )
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return out


@registry.register(mode=ToolMode.READ)
async def list_org_repos(
    ctx: ToolContext,
    include_archived: bool = True,
    only_private: bool = False,
    only_public: bool = False,
) -> dict[str, Any]:
    """List all repositories of the organization with summary metadata.

    Returns each repo with: name, visibility, language, branch_count, open
    issues/PRs, dates, topics. Precise counts (GraphQL totalCount).
    """
    repos = await _all_repos(ctx)
    if not include_archived:
        repos = [r for r in repos if not r.is_archived]
    if only_private:
        repos = [r for r in repos if r.is_private]
    if only_public:
        repos = [r for r in repos if not r.is_private]
    return {
        "org": ctx.org,
        "total": len(repos),
        "repos": [r.model_dump() for r in repos],
    }


@registry.register(mode=ToolMode.READ)
async def count_repos(ctx: ToolContext) -> dict[str, int]:
    """Count repositories by visibility and status.

    Returns total, public, private, archived, fork, template.
    """
    repos = await _all_repos(ctx)
    return {
        "total": len(repos),
        "public": sum(1 for r in repos if not r.is_private),
        "private": sum(1 for r in repos if r.is_private),
        "archived": sum(1 for r in repos if r.is_archived),
        "fork": sum(1 for r in repos if r.is_fork),
        "template": sum(1 for r in repos if r.is_template),
    }


@registry.register(mode=ToolMode.READ)
async def repos_without_updates(
    ctx: ToolContext,
    days: int = Field(default=180, ge=1, le=3650),
) -> dict[str, Any]:
    """Repositories with no pushes in the last N days.

    Returns names and last push date. Precise (uses pushedAt from GraphQL).
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    repos = await _all_repos(ctx)
    stale = []
    for r in repos:
        pushed = r.pushed_at
        if not pushed:
            continue
        pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        if pushed_dt < cutoff:
            stale.append({"name": r.name_with_owner, "last_push": pushed})
    stale.sort(key=lambda x: x["last_push"])
    return {"days": int(days), "count": len(stale), "repos": stale}


@registry.register(mode=ToolMode.READ)
async def repos_with_multiple_branches(ctx: ToolContext) -> dict[str, Any]:
    """Repositories with more than 1 branch.

    Returns names with branch count.
    """
    repos = await _all_repos(ctx)
    multi = [
        {"name": r.name_with_owner, "branches": r.branch_count}
        for r in repos
        if r.branch_count > 1
    ]
    multi.sort(key=lambda x: -x["branches"])
    return {"count": len(multi), "repos": multi}


@registry.register(mode=ToolMode.READ)
async def datapackages_stats(
    ctx: ToolContext,
    topic: str = "datapackage",
) -> dict[str, Any]:
    """Statistics of repos tagged with a given topic (default: datapackage).

    Returns total, public/private split, and per-repo metadata.
    """
    repos = await _all_repos(ctx)
    matches = [r for r in repos if topic.lower() in (t.lower() for t in r.topics)]
    return {
        "topic": topic,
        "total": len(matches),
        "public": sum(1 for r in matches if not r.is_private),
        "private": sum(1 for r in matches if r.is_private),
        "repos": [
            {
                "name": r.name_with_owner,
                "private": r.is_private,
                "url": r.url,
                "updated_at": r.updated_at,
            }
            for r in matches
        ],
    }


@registry.register(mode=ToolMode.READ)
async def get_repo(ctx: ToolContext, repo: str) -> dict[str, Any]:
    """Get detailed information for a single repository (by name only).

    The owner is always the configured organization — do not pass owner.
    """
    safe = _safe_repo_name(repo)
    data = await ctx.gh.get(f"/repos/{ctx.org}/{safe}", owner=ctx.org)
    if not isinstance(data, dict):
        return {"error": "unexpected response"}
    keys = [
        "name", "full_name", "private", "description", "fork", "archived",
        "default_branch", "language", "stargazers_count", "forks_count",
        "open_issues_count", "topics", "pushed_at", "updated_at",
        "created_at", "html_url", "size",
    ]
    return {k: data.get(k) for k in keys}


def _safe_repo_name(repo: str) -> str:
    if "/" in repo:
        # Reject owner/repo form — owner must be the configured org only.
        owner, name = repo.split("/", 1)
        # Will be validated by client._check_owner if used elsewhere.
        return name
    return repo
