"""User activity summary + per-org activity report (precise counts)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from gitinho_mcp.github.graphql import ORG_ID, ORG_MEMBERS, USER_CONTRIBUTIONS
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context
from gitinho_mcp.tools.comments import list_comments_by_user

_ONE_YEAR = timedelta(days=365)


def _to_iso(date_str: str | None, *, end: bool = False) -> str:
    if not date_str:
        # Default window: last 365 days (or now, for `until`).
        if end:
            return datetime.now(timezone.utc).isoformat()
        return (
            datetime.now(timezone.utc).replace(microsecond=0) - _ONE_YEAR
        ).isoformat()
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


async def _org_node_id(ctx: ToolContext) -> str:
    data = await ctx.gh.graphql(ORG_ID, {"org": ctx.org})
    return data["organization"]["id"]


async def _user_activity_summary(
    ctx: ToolContext,
    login: str,
    since: str | None,
    until: str | None,
) -> dict[str, Any]:
    """Shared implementation — called both by the MCP tool and the org report."""
    org_id = await _org_node_id(ctx)
    sfrom = _to_iso(since)
    suntil = _to_iso(until, end=True)
    contrib = await ctx.gh.graphql(
        USER_CONTRIBUTIONS,
        {"login": login, "from": sfrom, "to": suntil, "org": org_id},
    )
    coll = (contrib.get("user") or {}).get("contributionsCollection") or {}

    issue_comments, issue_q = await list_comments_by_user(
        ctx, "issue", login, sfrom, suntil, max_results=1000
    )
    pr_comments, pr_q = await list_comments_by_user(
        ctx, "pr", login, sfrom, suntil, max_results=1000
    )

    return {
        "login": login,
        "org": ctx.org,
        "since": sfrom,
        "until": suntil,
        "commits": coll.get("totalCommitContributions", 0),
        "issues_created": coll.get("totalIssueContributions", 0),
        "prs_created": coll.get("totalPullRequestContributions", 0),
        "pr_reviews": coll.get("totalPullRequestReviewContributions", 0),
        "repositories_created": coll.get("totalRepositoryContributions", 0),
        "issue_comments_authored": len(issue_comments),
        "pr_comments_authored": len(pr_comments),
        "source_query": {
            "commits": "GraphQL user.contributionsCollection.totalCommitContributions",
            "issues_created": "GraphQL user.contributionsCollection.totalIssueContributions",
            "prs_created": "GraphQL user.contributionsCollection.totalPullRequestContributions",
            "pr_reviews": "GraphQL user.contributionsCollection.totalPullRequestReviewContributions",
            "repositories_created": "GraphQL user.contributionsCollection.totalRepositoryContributions",
            "issue_comments_authored": (
                f"search candidates: '{issue_q}' "
                "then REST /repos/{owner}/{repo}/issues/{n}/comments "
                "filtered by user.login + created_at in [since, until]"
            ),
            "pr_comments_authored": (
                f"search candidates: '{pr_q}' "
                "then REST /repos/{owner}/{repo}/issues/{n}/comments "
                "filtered by user.login + created_at in [since, until]"
            ),
        },
    }


@mcp.tool()
async def user_activity_summary(
    login: str,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Activity counts for a user inside the org for a date range.

    Counts come from GitHub's `contributionsCollection` (commits, issues,
    PRs, reviews) plus per-comment REST iteration for accurate
    `issue_comments_authored` / `pr_comments_authored`. `since` / `until`
    are ISO dates; both default to a 365-day window ending now.

    The returned `source_query` field documents which endpoint/query
    produced each metric — use it to reconcile numbers against the raw
    `list_issue_comments_by_user` / `list_pr_comments_by_user` tools when
    something looks off.
    """
    ctx = await get_context()
    return await _user_activity_summary(ctx, login, since, until)


@mcp.tool()
async def org_users_activity_report(
    since: str | None = None,
    until: str | None = None,
    max_members: int = 200,
) -> dict[str, Any]:
    """Per-member activity report from GitHub's `contributionsCollection`.

    Comment counts are intentionally NOT included here — accurate per-user
    comment counting requires per-issue REST iteration that scales poorly
    across the whole membership. Use `user_activity_summary` or the
    `list_*_comments_by_user` tools for that.
    """
    ctx = await get_context()
    org_id = await _org_node_id(ctx)
    sfrom = _to_iso(since)
    suntil = _to_iso(until, end=True)

    members: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        data = await ctx.gh.graphql(ORG_MEMBERS, {"org": ctx.org, "after": cursor})
        page = data["organization"]["membersWithRole"]
        for n in page["nodes"]:
            members.append({"login": n["login"], "name": n.get("name")})
        if not page["pageInfo"]["hasNextPage"] or len(members) >= max_members:
            break
        cursor = page["pageInfo"]["endCursor"]
    members = members[:max_members]

    sem = asyncio.Semaphore(5)

    async def _one(member: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            contrib = await ctx.gh.graphql(
                USER_CONTRIBUTIONS,
                {"login": member["login"], "from": sfrom, "to": suntil, "org": org_id},
            )
            coll = (contrib.get("user") or {}).get("contributionsCollection") or {}
            return {
                "login": member["login"],
                "name": member.get("name"),
                "commits": coll.get("totalCommitContributions", 0),
                "issues_created": coll.get("totalIssueContributions", 0),
                "prs_created": coll.get("totalPullRequestContributions", 0),
                "pr_reviews": coll.get("totalPullRequestReviewContributions", 0),
            }

    rows = await asyncio.gather(*[_one(m) for m in members])
    return {
        "org": ctx.org,
        "since": sfrom,
        "until": suntil,
        "members_total": len(rows),
        "rows": rows,
        "_chat_table": {
            "title": f"Atividade dos membros — {ctx.org}",
            "description": f"{len(rows)} membros — janela {sfrom[:10]} a {suntil[:10]}",
            "data_field": "rows",
            "columns": [
                {"key": "login", "label": "Login", "type": "string"},
                {"key": "name", "label": "Nome", "type": "string"},
                {"key": "commits", "label": "Commits", "type": "number"},
                {"key": "issues_created", "label": "Issues", "type": "number"},
                {"key": "prs_created", "label": "PRs", "type": "number"},
                {"key": "pr_reviews", "label": "Reviews", "type": "number"},
            ],
        },
    }
