"""Pull-request counts, listing, last-by-user, search, repo-listing, detail."""

from __future__ import annotations

import httpx

from typing import Any

from gitinho_mcp.github.graphql import ORG_OPEN_PRS
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context


# Same defense as in code_search: never let the agent inject `org:`, `user:`
# or `repo:` qualifiers into a query — the App installation token grants
# access to repos in multiple orgs sometimes, and a malicious or hallucinated
# query could otherwise leak across the boundary. We strip them client-side
# and re-add a canonical `org:<ALLOWED_ORG>` (or repo: when scoping).
_RESERVED_QUALIFIERS = ("org:", "user:", "repo:")


def _strip_scope_qualifiers(query: str) -> list[str]:
    return [
        tok
        for tok in (query or "").strip().split()
        if not any(tok.lower().startswith(q) for q in _RESERVED_QUALIFIERS)
    ]


def _pr_row(it: dict[str, Any]) -> dict[str, Any]:
    """Shape a /search/issues PR item into the row we expose in _chat_table."""
    return {
        "title": it.get("title"),
        "repo": it.get("repository_url", "").split("/repos/")[-1],
        "number": it.get("number"),
        "state": it.get("state"),
        "merged": bool((it.get("pull_request") or {}).get("merged_at")),
        "author": (it.get("user") or {}).get("login"),
        "created_at": it.get("created_at"),
        "closed_at": it.get("closed_at"),
        "labels": [
            lbl.get("name") for lbl in (it.get("labels") or []) if lbl.get("name")
        ],
        "url": it.get("html_url"),
    }


_PR_TABLE_COLUMNS = [
    {"key": "title", "label": "Título", "type": "string"},
    {"key": "repo", "label": "Repositório", "type": "string"},
    {"key": "number", "label": "#", "type": "number"},
    {"key": "state", "label": "Estado", "type": "string"},
    {"key": "merged", "label": "Merged", "type": "boolean"},
    {"key": "author", "label": "Autor", "type": "string"},
    {"key": "created_at", "label": "Criado em", "type": "date"},
    {"key": "closed_at", "label": "Fechado em", "type": "date"},
    {"key": "url", "label": "URL", "type": "string"},
]


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


@mcp.tool()
async def search_prs(
    query: str,
    state: str | None = None,
    label: str | None = None,
    base: str | None = None,
    head: str | None = None,
    repo: str | None = None,
    since: str | None = None,
    until: str | None = None,
    max_results: int = 200,
) -> dict[str, Any]:
    """Free-text search across pull requests in the org.

    Analog of `search_issues` but always pinned to `is:pr`. Use this for any
    question that isn't covered by the more specific PR tools — e.g. "PRs
    mencionando 'datapackage'", "PRs com label 'bug'", "PRs contra a base
    `develop`", "PRs feitos contra o head `feature/x`".

    Filters (all optional):
      - `state`: "open" | "closed" | "merged"
      - `label`: GitHub label name (added as `label:"<x>"`)
      - `base` / `head`: target/source branch
      - `repo`: scope to a single repo (name only, no owner)
      - `since` / `until`: ISO date (YYYY-MM-DD) bounding `created`

    Defense: any `org:`/`user:`/`repo:` qualifier the agent puts inside
    `query` is stripped — only the parameters above can scope the search.
    The query is always re-anchored to `org:<ALLOWED_ORG>` (or
    `repo:<ALLOWED_ORG>/<repo>` when `repo` is given).

    `max_results` is clamped to 1..1000 (GitHub Search API cap).
    """
    ctx = await get_context()
    tokens = _strip_scope_qualifiers(query)
    tokens.append("is:pr")
    if repo:
        tokens.append(f"repo:{ctx.org}/{repo}")
    else:
        tokens.append(f"org:{ctx.org}")
    if state in ("open", "closed", "merged"):
        tokens.append(f"is:{state}")
    if label:
        tokens.append(f'label:"{label}"')
    if base:
        tokens.append(f"base:{base}")
    if head:
        tokens.append(f"head:{head}")
    if since:
        tokens.append(f"created:>={since}")
    if until:
        tokens.append(f"created:<={until}")
    q = " ".join(tokens)
    cap = max(1, min(1000, int(max_results)))
    items = await _search_issues_all(ctx, q, max_items=cap)
    rows = [_pr_row(it) for it in items]
    return {
        "query": q,
        "total": len(rows),
        "prs": rows,
        "_chat_table": {
            "title": f"Busca de PRs: {query}",
            "description": (
                f"{len(rows)} resultados"
                + (f" — repo {repo}" if repo else "")
                + (f" — estado {state}" if state else "")
            ),
            "data_field": "prs",
            "columns": _PR_TABLE_COLUMNS,
        },
    }


@mcp.tool()
async def list_prs_by_repo(
    repo: str,
    state: str = "all",
    base: str | None = None,
    head: str | None = None,
    author: str | None = None,
    label: str | None = None,
    since: str | None = None,
    until: str | None = None,
    max_results: int = 200,
) -> dict[str, Any]:
    """List PRs of a single repo, with filters.

    The repo-scoped counterpart of `list_prs_by_user`. Pin defensively to
    `repo:<ALLOWED_ORG>/<repo>` so even if `repo` is misnamed we never
    bleed into another org.

    `state`: "open" | "closed" | "merged" | "all" (default).
    `base` / `head`: target/source branch.
    `author` / `label`: optional GitHub Search qualifiers.
    `since` / `until`: ISO date (YYYY-MM-DD) bounding `created`.
    `max_results` clamped to 1..1000.
    """
    ctx = await get_context()
    tokens = ["is:pr", f"repo:{ctx.org}/{repo}"]
    if state in ("open", "closed", "merged"):
        tokens.append(f"is:{state}")
    if base:
        tokens.append(f"base:{base}")
    if head:
        tokens.append(f"head:{head}")
    if author:
        tokens.append(f"author:{author}")
    if label:
        tokens.append(f'label:"{label}"')
    if since:
        tokens.append(f"created:>={since}")
    if until:
        tokens.append(f"created:<={until}")
    q = " ".join(tokens)
    cap = max(1, min(1000, int(max_results)))
    items = await _search_issues_all(ctx, q, max_items=cap)
    rows = [_pr_row(it) for it in items]
    return {
        "repo": f"{ctx.org}/{repo}",
        "query": q,
        "state": state,
        "total": len(rows),
        "prs": rows,
        "_chat_table": {
            "title": f"PRs de {ctx.org}/{repo}",
            "description": (
                f"{len(rows)} PRs — estado: {state}"
                + (f" — base {base}" if base else "")
                + (f" — autor @{author}" if author else "")
                + (f" — label '{label}'" if label else "")
            ),
            "data_field": "prs",
            "columns": _PR_TABLE_COLUMNS,
        },
    }


@mcp.tool()
async def list_prs_awaiting_review(
    login: str,
    repo: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """List open PRs where `login` was requested as reviewer and hasn't reviewed yet.

    Uses GitHub Search's `review-requested:<login>` qualifier — covers PRs
    awaiting a specific user's review (individual requests). Does NOT cover
    team-review requests (`team-review-requested:<team>`); add that as a
    follow-up if/when needed.

    Returns only open PRs.
    """
    ctx = await get_context()
    tokens = ["is:pr", "is:open", f"review-requested:{login}"]
    if repo:
        tokens.append(f"repo:{ctx.org}/{repo}")
    else:
        tokens.append(f"org:{ctx.org}")
    q = " ".join(tokens)
    cap = max(1, min(1000, int(max_results)))
    items = await _search_issues_all(ctx, q, max_items=cap)
    rows = [_pr_row(it) for it in items]
    return {
        "login": login,
        "query": q,
        "total": len(rows),
        "prs": rows,
        "_chat_table": {
            "title": f"PRs aguardando review de @{login}",
            "description": (
                f"{len(rows)} PRs abertos"
                + (f" em {ctx.org}/{repo}" if repo else f" em {ctx.org}")
            ),
            "data_field": "prs",
            "columns": _PR_TABLE_COLUMNS,
        },
    }


def _truncate(text: str | None, limit: int = 4000) -> str | None:
    """Cap a long body to keep the LLM context cheap; mark when truncated."""
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated, original {len(text)} chars]"


@mcp.tool()
async def get_pr(
    repo: str,
    number: int,
    include_files: bool = False,
    include_reviews: bool = False,
) -> dict[str, Any]:
    """Detailed view of a single PR (read-only).

    Always returns the core fields (title, body, state, merged, author, base,
    head, labels, requested_reviewers, mergeable_state, statistics).

    Optional, off by default to keep responses cheap:
      - `include_files=True`: list of changed files with additions/deletions.
      - `include_reviews=True`: list of submitted reviews (author, state, body).

    Body is truncated at 4000 chars (marker appended); raw file diffs are NOT
    included — the agent can grab them from the GitHub URL if asked.
    """
    ctx = await get_context()
    try:
        pr = await ctx.gh.get(
            f"/repos/{ctx.org}/{repo}/pulls/{number}", owner=ctx.org
        )
    except httpx.HTTPStatusError as exc:
        return {
            "repo": f"{ctx.org}/{repo}",
            "number": number,
            "found": False,
            "error": f"HTTP {exc.response.status_code}",
        }
    if not isinstance(pr, dict):
        return {
            "repo": f"{ctx.org}/{repo}",
            "number": number,
            "found": False,
            "error": "unexpected response shape",
        }

    user = pr.get("user") or {}
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    out: dict[str, Any] = {
        "repo": f"{ctx.org}/{repo}",
        "number": pr.get("number"),
        "found": True,
        "title": pr.get("title"),
        "body": _truncate(pr.get("body")),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "merged": pr.get("merged"),
        "merged_at": pr.get("merged_at"),
        "mergeable_state": pr.get("mergeable_state"),
        "author": user.get("login"),
        "base_branch": base.get("ref"),
        "head_branch": head.get("ref"),
        "head_repo": (head.get("repo") or {}).get("full_name"),
        "labels": [
            lbl.get("name") for lbl in (pr.get("labels") or []) if lbl.get("name")
        ],
        "requested_reviewers": [
            r.get("login") for r in (pr.get("requested_reviewers") or []) if r.get("login")
        ],
        "comments": pr.get("comments"),
        "review_comments": pr.get("review_comments"),
        "commits": pr.get("commits"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files": pr.get("changed_files"),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "closed_at": pr.get("closed_at"),
        "url": pr.get("html_url"),
    }

    if include_files:
        try:
            files = await ctx.gh.get(
                f"/repos/{ctx.org}/{repo}/pulls/{number}/files",
                params={"per_page": 100},
                owner=ctx.org,
            )
        except httpx.HTTPStatusError as exc:
            files = {"_error": f"HTTP {exc.response.status_code}"}
        if isinstance(files, list):
            out["files"] = [
                {
                    "filename": f.get("filename"),
                    "status": f.get("status"),
                    "additions": f.get("additions"),
                    "deletions": f.get("deletions"),
                    "changes": f.get("changes"),
                }
                for f in files
            ]
        else:
            out["files_error"] = files

    if include_reviews:
        try:
            reviews = await ctx.gh.get(
                f"/repos/{ctx.org}/{repo}/pulls/{number}/reviews",
                params={"per_page": 100},
                owner=ctx.org,
            )
        except httpx.HTTPStatusError as exc:
            reviews = {"_error": f"HTTP {exc.response.status_code}"}
        if isinstance(reviews, list):
            out["reviews"] = [
                {
                    "author": (r.get("user") or {}).get("login"),
                    "state": r.get("state"),
                    "body": _truncate(r.get("body"), 1000),
                    "submitted_at": r.get("submitted_at"),
                }
                for r in reviews
            ]
        else:
            out["reviews_error"] = reviews

    return out
