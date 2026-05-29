"""Repository-level tools (counts, listings, branches, datapackages, get)."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from gitinho_mcp.github.graphql import ORG_REPOS_PAGE
from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context

# Hard cap on file content returned to the LLM. 512 KB ≈ 130k tokens — already
# larger than any README or manifest file we expect to read; bigger inputs
# would dominate the context window and rarely help answer the question.
MAX_FILE_BYTES = 512 * 1024


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


async def _code_search_all(
    ctx: ToolContext, query: str, max_items: int = 500
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    per_page = 100
    while len(out) < max_items:
        data = await ctx.gh.get(
            "/search/code",
            params={"q": query, "per_page": per_page, "page": page},
        )
        if not isinstance(data, dict):
            break
        items = data.get("items") or []
        out.extend(items)
        if len(items) < per_page:
            break
        page += 1
    return out


def _safe_repo_name(repo: str) -> str:
    # Reject owner/repo form — the owner is always the configured org.
    if "/" in repo:
        _, name = repo.split("/", 1)
        return name
    return repo


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


@mcp.tool()
async def list_org_repos(
    include_archived: bool = True,
    only_private: bool = False,
    only_public: bool = False,
) -> dict[str, Any]:
    """List all repositories of the organization with summary metadata.

    Returns each repo with: name, visibility, language, branch_count, open
    issues/PRs, dates, topics. Precise counts (GraphQL totalCount).
    """
    ctx = await get_context()
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


@mcp.tool()
async def repos_without_updates(days: int = 180) -> dict[str, Any]:
    """Repositories with no pushes in the last N days.

    `days` is clamped to the range 1..3650. Returns names and last push
    date (precise, from GraphQL `pushedAt`).
    """
    ctx = await get_context()
    days = max(1, min(3650, int(days)))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    repos = await _all_repos(ctx)
    stale: list[dict[str, Any]] = []
    for r in repos:
        if not r.pushed_at:
            continue
        pushed_dt = datetime.fromisoformat(r.pushed_at.replace("Z", "+00:00"))
        if pushed_dt < cutoff:
            stale.append({"name": r.name_with_owner, "last_push": r.pushed_at})
    stale.sort(key=lambda x: x["last_push"])
    return {"days": days, "count": len(stale), "repos": stale}


@mcp.tool()
async def repos_with_multiple_branches() -> dict[str, Any]:
    """Repositories with more than 1 branch. Returns names with branch count."""
    ctx = await get_context()
    repos = await _all_repos(ctx)
    multi = [
        {"name": r.name_with_owner, "branches": r.branch_count}
        for r in repos
        if r.branch_count > 1
    ]
    multi.sort(key=lambda x: -x["branches"])
    return {"count": len(multi), "repos": multi}


@mcp.tool()
async def datapackages_stats(topic: str = "datapackage") -> dict[str, Any]:
    """List repos tagged with a given GitHub topic (default: "datapackage").

    NOT the canonical way to find Frictionless Data datapackages — topics
    are optional and many real datapackages are not tagged. Use this tool
    only when the user EXPLICITLY asks to filter by topic. For the default
    case of "find datapackages", use `find_datapackages` instead, which
    checks the canonical criterion (presence of `datapackage.json` at the
    repo root).
    """
    ctx = await get_context()
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


@mcp.tool()
async def find_datapackages(include_archived: bool = False) -> dict[str, Any]:
    """Find Frictionless Data datapackages in the organization (CANONICAL).

    Identifies datapackages by the canonical criterion: presence of the
    file `datapackage.json` at the repository root (per the Frictionless
    Data specification, https://frictionlessdata.io).

    Use this tool for ANY question about datapackages / frictionless /
    "data packages" of the organization, unless the user explicitly asks
    to filter by GitHub topic (in which case use `datapackages_stats`).
    """
    ctx = await get_context()
    items = await _code_search_all(
        ctx, f"filename:datapackage.json org:{ctx.org}"
    )
    by_repo: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.get("path") != "datapackage.json":
            continue
        repo = item.get("repository") or {}
        full_name = repo.get("full_name")
        if not full_name or full_name in by_repo:
            continue
        by_repo[full_name] = {
            "name": full_name,
            "private": repo.get("private"),
            "archived": None,
            "url": repo.get("html_url"),
            "description": repo.get("description"),
        }

    try:
        all_repos = {r.name_with_owner: r for r in await _all_repos(ctx)}
    except Exception:  # noqa: BLE001
        all_repos = {}

    enriched: list[dict[str, Any]] = []
    for full_name, info in by_repo.items():
        r = all_repos.get(full_name)
        if r is not None:
            info["archived"] = r.is_archived
            info["last_push"] = r.pushed_at
            info["default_branch"] = r.default_branch
            info["topics"] = r.topics
        if not include_archived and info.get("archived"):
            continue
        enriched.append(info)

    enriched.sort(key=lambda x: x.get("last_push") or "", reverse=True)
    return {
        "criterion": "datapackage.json at repo root (Frictionless Data spec)",
        "org": ctx.org,
        "total": len(enriched),
        "public": sum(1 for r in enriched if r.get("private") is False),
        "private": sum(1 for r in enriched if r.get("private") is True),
        "include_archived": include_archived,
        "repos": enriched,
    }


@mcp.tool()
async def get_repo(repo: str) -> dict[str, Any]:
    """Get detailed information for a single repository (by name only).

    The owner is always the configured organization — do not pass owner.
    """
    ctx = await get_context()
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


def _decode_content_payload(
    payload: dict[str, Any], ref: str | None
) -> dict[str, Any]:
    """Decode a GitHub /contents or /readme JSON response into text.

    Returns the standard `{"ok": ...}` envelope. Rejects directories,
    oversize files (>MAX_FILE_BYTES), unsupported encodings, and binary
    content that does not decode as UTF-8.
    """
    if payload.get("type") == "dir" or isinstance(payload, list):
        return {"ok": False, "error": "path is a directory, not a file"}

    size = int(payload.get("size") or 0)
    if size > MAX_FILE_BYTES:
        return {
            "ok": False,
            "error": (
                f"file too large ({size} bytes, max {MAX_FILE_BYTES})"
            ),
            "size_bytes": size,
            "path": payload.get("path"),
            "html_url": payload.get("html_url"),
        }

    encoding = payload.get("encoding")
    raw_b64 = payload.get("content") or ""
    if encoding != "base64" or not raw_b64:
        # GitHub returns encoding="none" with empty content for files in the
        # 1–100 MB range. Anything else is unexpected — surface as error.
        return {
            "ok": False,
            "error": (
                f"unsupported encoding '{encoding}' "
                "(file may be too large for the contents API)"
            ),
            "size_bytes": size,
            "path": payload.get("path"),
            "html_url": payload.get("html_url"),
        }

    try:
        raw = base64.b64decode(raw_b64, validate=False)
    except (binascii.Error, ValueError) as exc:
        return {"ok": False, "error": f"invalid base64: {exc}"}

    if len(raw) > MAX_FILE_BYTES:
        return {
            "ok": False,
            "error": (
                f"file too large after decode ({len(raw)} bytes, "
                f"max {MAX_FILE_BYTES})"
            ),
            "size_bytes": len(raw),
            "path": payload.get("path"),
            "html_url": payload.get("html_url"),
        }

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "ok": False,
            "error": "binary file (not valid UTF-8)",
            "size_bytes": len(raw),
            "path": payload.get("path"),
            "html_url": payload.get("html_url"),
        }

    return {
        "ok": True,
        "name": payload.get("name"),
        "path": payload.get("path"),
        "sha": payload.get("sha"),
        "size_bytes": len(raw),
        "ref": ref,
        "html_url": payload.get("html_url"),
        "download_url": payload.get("download_url"),
        "content": text,
    }


@mcp.tool()
async def get_repo_readme(repo: str, ref: str | None = None) -> dict[str, Any]:
    """Read the README of a repository as text.

    Use this whenever a user asks what a repo is *about*, what it does,
    or how to use it — the README is the primary source. The repo
    metadata description (from `get_repo`) is often empty; the README is
    not.

    The owner is always the configured organization — pass only the repo
    name. `ref` is optional (branch, tag, or commit SHA); when omitted
    GitHub returns the default branch.

    Errors return `{"ok": false, "error": "..."}`. Files over
    ~512 KB are rejected to protect the LLM context window — fall back
    to opening the HTML page if that happens.
    """
    ctx = await get_context()
    safe = _safe_repo_name(repo)
    params = {"ref": ref} if ref else None
    try:
        data = await ctx.gh.get(
            f"/repos/{ctx.org}/{safe}/readme",
            params=params,
            owner=ctx.org,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"ok": False, "error": "repo or README not found"}
        return {
            "ok": False,
            "error": f"github error {exc.response.status_code}",
        }
    if not isinstance(data, dict):
        return {"ok": False, "error": "unexpected response shape"}
    return _decode_content_payload(data, ref)


@mcp.tool()
async def get_file_content(
    repo: str, path: str, ref: str | None = None
) -> dict[str, Any]:
    """Read the text content of a single file from a repository.

    Use this to inspect specific files — `mkdocs.yml`, `pyproject.toml`,
    `datapackage.json`, `docs/index.md`, etc. — when their content
    matters to the user's question. For the README specifically, prefer
    `get_repo_readme` (it works regardless of filename/case).

    The owner is always the configured organization — pass only the repo
    name. `path` is the file path inside the repo (no leading slash).
    `ref` is optional (branch, tag, or commit SHA).

    Errors return `{"ok": false, "error": "..."}`. Directories,
    binary files, and files over ~512 KB are rejected — for those,
    return the `html_url` so the user can open it directly.
    """
    ctx = await get_context()
    safe = _safe_repo_name(repo)
    clean_path = path.lstrip("/")
    if not clean_path:
        return {"ok": False, "error": "path is required"}
    encoded_path = quote(clean_path, safe="/")
    params = {"ref": ref} if ref else None
    try:
        data = await ctx.gh.get(
            f"/repos/{ctx.org}/{safe}/contents/{encoded_path}",
            params=params,
            owner=ctx.org,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"ok": False, "error": "file or repo not found"}
        return {
            "ok": False,
            "error": f"github error {exc.response.status_code}",
        }
    if isinstance(data, list):
        return {
            "ok": False,
            "error": "path is a directory, not a file",
            "entries": [
                {"name": e.get("name"), "type": e.get("type")} for e in data
            ],
        }
    if not isinstance(data, dict):
        return {"ok": False, "error": "unexpected response shape"}
    return _decode_content_payload(data, ref)
