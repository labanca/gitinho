"""Issue/PR comment listings by user, scoped to a date range.

GitHub's `/search/issues` only knows about issues/PRs, not the comments
attached to them — `commenter:<login>` filters parent issues, and
`created:` / `updated:` constrain those parents' dates, not the comment
dates. Counting actual comments authored in a window therefore requires:

  1. Use search to find candidate parents the user commented on (cheap,
     ~1 call narrowed by `updated:>=since`).
  2. For each parent, fetch its comments via REST and filter to those
     whose `user.login` matches and `created_at` falls in [since, until].

This module exposes that helper plus two MCP tools that surface the raw
list (useful for traceability when the summary's counts look surprising).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context
from gitinho_mcp.tools.pulls import _search_issues_all


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _date_only(s: str | None) -> str | None:
    if not s:
        return None
    return s[:10]


async def list_comments_by_user(
    ctx: ToolContext,
    kind: str,
    login: str,
    since: str | None,
    until: str | None,
    max_results: int = 1000,
) -> tuple[list[dict[str, Any]], str]:
    """Return (comments, search_query). `kind` is "issue" or "pr"."""
    if kind not in ("issue", "pr"):
        raise ValueError(f"kind must be 'issue' or 'pr', got {kind!r}")
    since_dt = _parse_iso(since)
    until_dt = _parse_iso(until)
    login_l = login.lower()

    q_parts = [f"is:{kind}", f"commenter:{login}", f"org:{ctx.org}"]
    if since:
        q_parts.append(f"updated:>={_date_only(since)}")
    q = " ".join(q_parts)
    candidates = await _search_issues_all(ctx, q, max_items=1000)

    out: list[dict[str, Any]] = []
    for cand in candidates:
        repo_full = cand["repository_url"].split("/repos/")[-1]
        number = cand["number"]
        async for c in ctx.gh.paginate(
            f"/repos/{repo_full}/issues/{number}/comments",
            params={"per_page": 100},
            owner=ctx.org,
        ):
            user = (c.get("user") or {}).get("login", "")
            if user.lower() != login_l:
                continue
            created_at = c.get("created_at")
            if created_at:
                cdt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if since_dt and cdt < since_dt:
                    continue
                if until_dt and cdt > until_dt:
                    continue
            out.append(
                {
                    "repo": repo_full,
                    "parent_number": number,
                    "parent_title": cand.get("title"),
                    "parent_kind": kind,
                    "comment_id": c.get("id"),
                    "url": c.get("html_url"),
                    "created_at": created_at,
                    "updated_at": c.get("updated_at"),
                    "body_preview": (c.get("body") or "")[:200],
                }
            )
            if len(out) >= max_results:
                return out, q
    return out, q


@mcp.tool()
async def list_issue_comments_by_user(
    login: str,
    since: str | None = None,
    until: str | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """List issue comments authored by `login` between `since` and `until`.

    Accurate at the *comment* level (unlike `commenter:` search, which
    returns parent issues). `since` / `until` are ISO dates (YYYY-MM-DD
    or full ISO timestamps). `max_results` is clamped to 1..1000.
    """
    ctx = await get_context()
    cap = max(1, min(1000, int(max_results)))
    comments, q = await list_comments_by_user(
        ctx, "issue", login, since, until, max_results=cap
    )
    return {
        "login": login,
        "since": since,
        "until": until,
        "total": len(comments),
        "source_query": q,
        "comments": comments,
        "_chat_table": {
            "title": f"Comentários em issues por @{login}",
            "description": (
                f"{len(comments)} comentários"
                + (f" — desde {since}" if since else "")
                + (f" — até {until}" if until else "")
            ),
            "data_field": "comments",
            "columns": [
                {"key": "repo", "label": "Repositório", "type": "string"},
                {"key": "parent_number", "label": "Issue #", "type": "number"},
                {"key": "parent_title", "label": "Título do issue", "type": "string"},
                {"key": "created_at", "label": "Criado em", "type": "date"},
                {"key": "body_preview", "label": "Trecho", "type": "string"},
                {"key": "url", "label": "URL", "type": "string"},
            ],
        },
    }


@mcp.tool()
async def list_pr_comments_by_user(
    login: str,
    since: str | None = None,
    until: str | None = None,
    max_results: int = 500,
) -> dict[str, Any]:
    """List PR conversation comments authored by `login` in [since, until].

    PR *review* (code-line) comments use a different endpoint and are NOT
    included here — this surfaces only the conversation/timeline comments
    that mirror issue comments.
    """
    ctx = await get_context()
    cap = max(1, min(1000, int(max_results)))
    comments, q = await list_comments_by_user(
        ctx, "pr", login, since, until, max_results=cap
    )
    return {
        "login": login,
        "since": since,
        "until": until,
        "total": len(comments),
        "source_query": q,
        "comments": comments,
        "_chat_table": {
            "title": f"Comentários em PRs por @{login}",
            "description": (
                f"{len(comments)} comentários"
                + (f" — desde {since}" if since else "")
                + (f" — até {until}" if until else "")
            ),
            "data_field": "comments",
            "columns": [
                {"key": "repo", "label": "Repositório", "type": "string"},
                {"key": "parent_number", "label": "PR #", "type": "number"},
                {"key": "parent_title", "label": "Título do PR", "type": "string"},
                {"key": "created_at", "label": "Criado em", "type": "date"},
                {"key": "body_preview", "label": "Trecho", "type": "string"},
                {"key": "url", "label": "URL", "type": "string"},
            ],
        },
    }
