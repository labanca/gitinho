"""Org-scoped GitHub code search.

Wraps `/search/code` (REST) and forces an `org:<ALLOWED_ORG>` qualifier so
the App installation token never bleeds searches into other orgs. The
endpoint is index-based — newly pushed code may take minutes to appear
and very-recently-created private repos can be silently missing — so the
tool returns the GitHub API's `incomplete_results` flag verbatim and the
agent should surface it to the user when true.
"""

from __future__ import annotations

from typing import Any

from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import get_context


_RESERVED_QUALIFIERS = ("org:", "user:", "repo:")


def _build_query(
    raw: str,
    org: str,
    repo: str | None,
    extension: str | None,
    path: str | None,
    language: str | None,
    filename: str | None,
) -> str:
    """Compose the final `/search/code` `q` parameter.

    Strips any user-supplied scope qualifiers so we always pin the search
    to `ALLOWED_ORG` (or a single repo within it). This is a defense-in-
    depth guarantee — without it a clever query could try to read code
    from another org the App might happen to be installed on.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("query must be non-empty")
    tokens = [
        tok for tok in raw.split()
        if not any(tok.lower().startswith(q) for q in _RESERVED_QUALIFIERS)
    ]
    if repo:
        tokens.append(f"repo:{org}/{repo}")
    else:
        tokens.append(f"org:{org}")
    if extension:
        tokens.append(f"extension:{extension.lstrip('.')}")
    if path:
        tokens.append(f"path:{path}")
    if language:
        tokens.append(f"language:{language}")
    if filename:
        tokens.append(f"filename:{filename}")
    return " ".join(tokens)


def _row(item: dict[str, Any]) -> dict[str, Any]:
    repo = item.get("repository") or {}
    return {
        "repo": repo.get("full_name") or repo.get("name"),
        "path": item.get("path"),
        "name": item.get("name"),
        "url": item.get("html_url"),
        "sha": item.get("sha"),
        "score": item.get("score"),
    }


@mcp.tool()
async def search_code(
    query: str,
    repo: str | None = None,
    extension: str | None = None,
    path: str | None = None,
    language: str | None = None,
    filename: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    """Free-text code search across the organization (REST /search/code).

    Use this to find string literals, function names, imports, configs —
    anything that lives in code rather than in issues/PRs. Examples:

      - `query="periodo="` — every file that contains the substring.
      - `query="from frictionless"` with `extension="py"` — Python files
        that import frictionless.
      - `query="datapackage"` with `filename="datapackage.json"` — every
        `datapackage.json` mentioning the word "datapackage".
      - `query="api_url"` with `repo="meu-projeto"` — restrict to one repo.

    The search is always scoped to the configured org (`org:<ALLOWED_ORG>`).
    Any `org:`, `user:` or `repo:` qualifier in `query` is stripped — use
    the `repo` parameter for repo scoping.

    Limits and caveats:
      - GitHub code search is index-based; very recent pushes may be
        missing. `incomplete_results` in the response signals this.
      - The endpoint is heavily rate-limited (10 req/min for authenticated
        callers). Prefer one focused query over many narrow probes.
      - Max 1000 results overall (10 pages × 100/page). `max_results`
        clamps to 1..1000; default 100.
      - Searches ONLY in repos where the GitHub App is installed and has
        `Contents: read`. Empty repos and forks may be excluded by GitHub.

    Returns `{query, total_count, incomplete_results, items, _chat_table}`.
    Each `item` row: `{repo, path, name, url, sha, score}`. Surface
    `incomplete_results=true` to the user so they know the index may be
    stale.
    """
    ctx = await get_context()
    cap = max(1, min(1000, int(max_results)))
    per_page = min(100, cap)
    q = _build_query(
        query, ctx.org, repo, extension, path, language, filename
    )

    items: list[dict[str, Any]] = []
    total_count = 0
    incomplete = False
    page = 1
    while len(items) < cap and page <= 10:
        res = await ctx.gh.get(
            "/search/code",
            params={"q": q, "per_page": per_page, "page": page},
            owner=ctx.org,
        )
        if not isinstance(res, dict):
            break
        total_count = res.get("total_count", total_count)
        incomplete = incomplete or bool(res.get("incomplete_results"))
        page_items = res.get("items") or []
        items.extend(page_items)
        if len(page_items) < per_page:
            break
        page += 1
    rows = [_row(it) for it in items[:cap]]

    return {
        "query": q,
        "total_count": total_count,
        "incomplete_results": incomplete,
        "returned": len(rows),
        "items": rows,
        "_chat_table": {
            "title": f"Busca de código: {query}",
            "description": (
                f"{len(rows)} arquivos retornados (total no índice: {total_count})"
                + (" — índice incompleto" if incomplete else "")
            ),
            "data_field": "items",
            "columns": [
                {"key": "repo", "label": "Repositório", "type": "string"},
                {"key": "path", "label": "Caminho", "type": "string"},
                {"key": "name", "label": "Arquivo", "type": "string"},
                {"key": "url", "label": "URL", "type": "string"},
            ],
        },
    }
