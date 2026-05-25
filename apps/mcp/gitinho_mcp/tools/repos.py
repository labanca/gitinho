"""Repository-level tools registered on the MCP server.

Phase 1 spike: only `count_repos`. The remaining repo tools (list,
without-updates, multi-branch, datapackages, get_repo) land in Phase 3.
"""

from __future__ import annotations

from pydantic import BaseModel

from gitinho_mcp.github.graphql import ORG_REPOS_PAGE
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context


class RepoSummary(BaseModel):
    name: str
    name_with_owner: str
    is_private: bool
    is_archived: bool
    is_fork: bool
    is_template: bool


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
                    is_private=node["isPrivate"],
                    is_archived=node["isArchived"],
                    is_fork=node["isFork"],
                    is_template=node["isTemplate"],
                )
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return out


@mcp.tool()
async def count_repos() -> dict[str, int]:
    """Count repositories of the configured organization by visibility and status.

    Returns total, public, private, archived, fork, template.
    """
    ctx = await get_context()
    repos = await _all_repos(ctx)
    return {
        "total": len(repos),
        "public": sum(1 for r in repos if not r.is_private),
        "private": sum(1 for r in repos if r.is_private),
        "archived": sum(1 for r in repos if r.is_archived),
        "fork": sum(1 for r in repos if r.is_fork),
        "template": sum(1 for r in repos if r.is_template),
    }
