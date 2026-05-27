"""User activity summary + per-org activity report (precise counts)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from gitinho_mcp.github.graphql import ORG_ID, ORG_MEMBERS, USER_CONTRIBUTIONS
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context

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

    async def _count(q_extra: str) -> int:
        q = f"{q_extra} org:{ctx.org} commenter:{login}"
        res = await ctx.gh.get(
            "/search/issues", params={"q": q, "per_page": 1}, owner=ctx.org
        )
        return (res or {}).get("total_count", 0) if isinstance(res, dict) else 0

    range_q = ""
    if since:
        range_q += f" created:>={since}"
    if until:
        range_q += f" created:<={until}"
    issue_comments_q = f"is:issue{range_q}"
    pr_comments_q = f"is:pr{range_q}"
    issue_comments, pr_comments = await asyncio.gather(
        _count(issue_comments_q),
        _count(pr_comments_q),
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
        "issue_comments_in_org": issue_comments,
        "pr_comments_in_org": pr_comments,
    }


@mcp.tool()
async def user_activity_summary(
    login: str,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Activity counts for a user inside the org for a date range.

    Uses GitHub's `contributionsCollection` (precise), plus searches to
    cover issue/PR comments. `since` / `until` are ISO dates; both default
    to a 365-day window ending now.
    """
    ctx = await get_context()
    return await _user_activity_summary(ctx, login, since, until)


@mcp.tool()
async def org_users_activity_report(
    since: str | None = None,
    until: str | None = None,
    max_members: int = 200,
) -> dict[str, Any]:
    """Full activity report: per-member counts of issues/PRs/commits/reviews.

    Returns rows ready for spreadsheet export. Bounded concurrency keeps
    this gentle on GitHub's rate limits.
    """
    ctx = await get_context()

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
            summary = await _user_activity_summary(
                ctx, member["login"], since, until
            )
            return {
                "login": member["login"],
                "name": member.get("name"),
                "commits": summary["commits"],
                "issues_created": summary["issues_created"],
                "prs_created": summary["prs_created"],
                "pr_reviews": summary["pr_reviews"],
                "issue_comments": summary["issue_comments_in_org"],
                "pr_comments": summary["pr_comments_in_org"],
            }

    rows = await asyncio.gather(*[_one(m) for m in members])
    return {
        "org": ctx.org,
        "since": since,
        "until": until,
        "members_total": len(rows),
        "rows": rows,
    }
