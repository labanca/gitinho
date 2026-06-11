"""Pull-request counts, listing, and last-by-user."""

from __future__ import annotations

from typing import Any

from gitinho_mcp.github.graphql import ORG_OPEN_PRS
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context


async def _search_issues_all(
    ctx: ToolContext, query: str, max_items: int = 1000
) -> list[dict[str, Any]]:
    """Paginate /search/issues — the API caps at 1000 results (10 pages of 100)."""
    out: list[dict[str, Any]] = []
    page = 1
    per_page = 100
    while len(out) < max_items and page <= 10:
        res = await ctx.gh.get(
            "/search/issues",
            params={
                "q": query,
                "per_page": per_page,
                "page": page,
                "sort": "created",
                "order": "desc",
            },
            owner=ctx.org,
        )
        if not isinstance(res, dict):
            break
        items = res.get("items") or []
        out.extend(items)
        if len(items) < per_page:
            break
        page += 1
    return out[:max_items]


@mcp.tool()
async def count_open_prs(repo: str | None = None) -> dict[str, Any]:
    """Count open PRs across the org, or for a single repo if `repo` given.

    Uses GraphQL totalCount — exact, not approximate.
    """
    ctx = await get_context()
    if repo:
        res = await ctx.gh.get(
            "/search/issues",
            params={"q": f"is:pr is:open repo:{ctx.org}/{repo}", "per_page": 1},
            owner=ctx.org,
        )
        return {
            "repo": f"{ctx.org}/{repo}",
            "open_prs": (res or {}).get("total_count", 0)
            if isinstance(res, dict)
            else 0,
        }

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
    return {
        "org": ctx.org,
        "total_open_prs": total,
        "per_repo": per_repo,
        "_chat_table": {
            "title": f"PRs abertos por repositório — {ctx.org}",
            "description": f"{total} PRs abertos em {len(per_repo)} repos",
            "data_field": "per_repo",
            "columns": [
                {"key": "repo", "label": "Repositório", "type": "string"},
                {"key": "open_prs", "label": "PRs abertos", "type": "number"},
            ],
        },
    }


@mcp.tool()
async def list_prs_by_user(
    login: str,
    state: str = "all",
    since: str | None = None,
    until: str | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """List pull requests created by a user in the organization.

    `state`: "open", "closed", "merged" or "all" (default).
    `since` / `until`: ISO date (YYYY-MM-DD) bounding the PR creation date.
    `max_results`: cap on returned items (default 500, max 1000 — GitHub
    Search API limit).

    Returns total and a list of PRs with title, repo, number, state,
    created_at, closed_at, merged, url.
    """
    ctx = await get_context()
    q_parts = ["is:pr", f"author:{login}", f"org:{ctx.org}"]
    if state == "open":
        q_parts.append("is:open")
    elif state == "closed":
        q_parts.append("is:closed")
    elif state == "merged":
        q_parts.append("is:merged")
    if since:
        q_parts.append(f"created:>={since}")
    if until:
        q_parts.append(f"created:<={until}")
    q = " ".join(q_parts)

    cap = max(1, min(1000, int(max_results)))
    items = await _search_issues_all(ctx, q, max_items=cap)
    rows = [
        {
            "title": it["title"],
            "repo": it["repository_url"].split("/repos/")[-1],
            "number": it["number"],
            "state": it["state"],
            "merged": bool(it.get("pull_request", {}).get("merged_at")),
            "created_at": it["created_at"],
            "closed_at": it.get("closed_at"),
            "url": it["html_url"],
        }
        for it in items
    ]
    return {
        "login": login,
        "query": q,
        "state": state,
        "since": since,
        "until": until,
        "total": len(rows),
        "prs": rows,
        "_chat_table": {
            "title": f"PRs de @{login} em {ctx.org}",
            "description": (
                f"{len(rows)} PRs — estado: {state}"
                + (f" — desde {since}" if since else "")
                + (f" — até {until}" if until else "")
            ),
            "data_field": "prs",
            "columns": [
                {"key": "title", "label": "Título", "type": "string"},
                {"key": "repo", "label": "Repositório", "type": "string"},
                {"key": "number", "label": "#", "type": "number"},
                {"key": "state", "label": "Estado", "type": "string"},
                {"key": "merged", "label": "Merged", "type": "boolean"},
                {"key": "created_at", "label": "Criado em", "type": "date"},
                {"key": "closed_at", "label": "Fechado em", "type": "date"},
                {"key": "url", "label": "URL", "type": "string"},
            ],
        },
    }


@mcp.tool()
async def last_pr_by_user(login: str) -> dict[str, Any]:
    """Most recent pull request created by a user in the org."""
    ctx = await get_context()
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
