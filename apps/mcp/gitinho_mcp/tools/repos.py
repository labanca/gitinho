"""Repository-level tools (counts, listings, branches, datapackages, get)."""

from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from gitinho_mcp.github.graphql import ORG_REPOS_PAGE, ORG_REPOS_WITH_DATAPACKAGE
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

    Uses GraphQL `repository.object(expression: "HEAD:datapackage.json")`
    to check existence on every org repo in one paginated query — does
    NOT use `/search/code`, which is index-based, misses recently created
    private repos, and silently omits results. The result is exhaustive
    and deterministic.

    Use this tool for ANY question about datapackages / frictionless /
    "data packages" of the organization, unless the user explicitly asks
    to filter by GitHub topic (in which case use `datapackages_stats`).
    """
    ctx = await get_context()
    enriched: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        data = await ctx.gh.graphql(
            ORG_REPOS_WITH_DATAPACKAGE, {"org": ctx.org, "after": cursor}
        )
        page = data["organization"]["repositories"]
        for node in page["nodes"]:
            if node.get("datapackage") is None:
                continue
            if not include_archived and node.get("isArchived"):
                continue
            enriched.append(
                {
                    "name": node["nameWithOwner"],
                    "private": node.get("isPrivate"),
                    "archived": node.get("isArchived"),
                    "url": node.get("url"),
                    "description": node.get("description"),
                    "last_push": node.get("pushedAt"),
                    "default_branch": (
                        (node.get("defaultBranchRef") or {}).get("name")
                    ),
                    "topics": [
                        n["topic"]["name"]
                        for n in (
                            node.get("repositoryTopics", {}).get("nodes") or []
                        )
                    ],
                    "datapackage_size_bytes": (node["datapackage"] or {}).get(
                        "byteSize"
                    ),
                }
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    enriched.sort(key=lambda x: x.get("last_push") or "", reverse=True)
    return {
        "criterion": "datapackage.json at repo root (Frictionless Data spec)",
        "source": "GraphQL repository.object(HEAD:datapackage.json) — exhaustive",
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


# Files commonly carrying repo-purpose information, tried best-effort by
# describe_repo. Order matters for readability of the response, not for
# semantics. Each one is optional — describe_repo never fails because a
# file is missing.
_DESCRIBE_REPO_AUX_FILES: tuple[str, ...] = (
    "docs/index.md",       # MkDocs landing page — usually the canonical description
    "docs/README.md",      # alternative MkDocs entry
    "mkdocs.yml",          # site_name + nav, useful even if rendered docs aren't fetched
    "pyproject.toml",      # Python project metadata (name, description, deps)
    "package.json",        # Node project metadata
    "datapackage.json",    # Frictionless Data datapackage descriptor
    "requirements.txt",    # Python deps fallback (when no pyproject)
)


async def _safe_get_repo_meta(ctx: ToolContext, name: str) -> dict[str, Any] | None:
    """get_repo wrapper for describe_repo: swallow 404s, surface None."""
    try:
        data = await ctx.gh.get(f"/repos/{ctx.org}/{name}", owner=ctx.org)
    except httpx.HTTPStatusError:
        return None
    if not isinstance(data, dict):
        return None
    keys = [
        "name", "full_name", "private", "description", "fork", "archived",
        "default_branch", "language", "stargazers_count", "forks_count",
        "open_issues_count", "topics", "pushed_at", "updated_at",
        "created_at", "html_url", "size", "homepage",
    ]
    return {k: data.get(k) for k in keys}


async def _safe_get_readme(ctx: ToolContext, name: str) -> dict[str, Any] | None:
    """get_repo_readme wrapper for describe_repo: returns the decoded
    envelope on success, None when missing."""
    try:
        data = await ctx.gh.get(f"/repos/{ctx.org}/{name}/readme", owner=ctx.org)
    except httpx.HTTPStatusError:
        return None
    if not isinstance(data, dict):
        return None
    decoded = _decode_content_payload(data, ref=None)
    return decoded if decoded.get("ok") else None


async def _safe_get_file(
    ctx: ToolContext, repo_name: str, path: str
) -> dict[str, Any] | None:
    """get_file_content wrapper for describe_repo: returns decoded text
    envelope on success, None when missing or undecodable."""
    encoded = quote(path, safe="/")
    try:
        data = await ctx.gh.get(
            f"/repos/{ctx.org}/{repo_name}/contents/{encoded}",
            owner=ctx.org,
        )
    except httpx.HTTPStatusError:
        return None
    if not isinstance(data, dict):
        return None
    decoded = _decode_content_payload(data, ref=None)
    return decoded if decoded.get("ok") else None


async def _safe_list_dir(
    ctx: ToolContext, repo_name: str, path: str = ""
) -> list[dict[str, Any]] | None:
    """contents listing wrapper for describe_repo: returns a list of
    {name, type, size} entries or None when missing/invalid."""
    suffix = f"/{quote(path.strip('/'), safe='/')}" if path.strip("/") else ""
    try:
        data = await ctx.gh.get(
            f"/repos/{ctx.org}/{repo_name}/contents{suffix}",
            owner=ctx.org,
        )
    except httpx.HTTPStatusError:
        return None
    if not isinstance(data, list):
        return None
    return [
        {
            "name": e.get("name"),
            "type": e.get("type"),  # "file", "dir", "symlink", "submodule"
            "size": e.get("size"),
            "path": e.get("path"),
        }
        for e in data
    ]


@mcp.tool()
async def list_repo_contents(
    repo: str, path: str = "", ref: str | None = None
) -> dict[str, Any]:
    """List files and directories at a path in a repository.

    **USE THIS to navigate a repo when you don't know its structure** —
    instead of guessing paths like `src/X.py` or `dpm/manager.py` and
    getting 404s, list the directory and pick a real entry. Mirrors
    what a developer does when exploring an unfamiliar repo.

    Typical flow for "describe / analyze repo X" when `describe_repo`
    alone isn't enough:
    1. `list_repo_contents(repo)` — see top-level files and folders.
    2. Pick promising folders (`src/`, `lib/`, `docs/`, name-of-repo,
       etc.) and `list_repo_contents(repo, "src")` to drill in.
    3. Once you spot a real file, `get_file_content(repo, path)`.

    `path` defaults to the repo root. `ref` is optional (branch/tag/SHA).
    Returns `{ok, repo, path, entries: [{name, type, size, path}], ...}`
    where `type` is one of `"file"`, `"dir"`, `"symlink"`, `"submodule"`.

    Errors return `{"ok": false, "error": "..."}` — e.g. when the path
    points to a file (use `get_file_content`) or doesn't exist.
    """
    ctx = await get_context()
    safe = _safe_repo_name(repo)
    clean_path = path.strip("/")
    suffix = f"/{quote(clean_path, safe='/')}" if clean_path else ""
    params = {"ref": ref} if ref else None
    try:
        data = await ctx.gh.get(
            f"/repos/{ctx.org}/{safe}/contents{suffix}",
            params=params,
            owner=ctx.org,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {
                "ok": False,
                "error": "repo or path not found",
                "repo": safe,
                "path": clean_path or "",
            }
        return {
            "ok": False,
            "error": f"github error {exc.response.status_code}",
        }
    if isinstance(data, dict):
        return {
            "ok": False,
            "error": "path is a file, not a directory — use get_file_content",
            "repo": safe,
            "path": clean_path or "",
        }
    if not isinstance(data, list):
        return {"ok": False, "error": "unexpected response shape"}
    entries = [
        {
            "name": e.get("name"),
            "type": e.get("type"),
            "size": e.get("size"),
            "path": e.get("path"),
        }
        for e in data
    ]
    return {
        "ok": True,
        "repo": safe,
        "path": clean_path or "",
        "ref": ref,
        "total": len(entries),
        "entries": entries,
    }


@mcp.tool()
async def describe_repo(repo: str) -> dict[str, Any]:
    """One-call full description of a repository — purpose, content, manifests, structure.

    **USE THIS for any question of the form "what is the repo X about",
    "describe repo X", "do que se trata X", "what does X do",
    "análise completa de X".**

    Prefer this over chaining `get_repo` + `get_repo_readme` +
    `get_file_content` + `list_repo_contents` manually — one call
    fetches everything in parallel and tolerates missing pieces:

    - `metadata` — owner/visibility/language/dates/stars (same shape as
      `get_repo`).
    - `readme` — README.md decoded as text (or `null` if absent).
    - `aux_files` — dict mapping filename → decoded text for files
      commonly carrying purpose info: `docs/index.md` (MkDocs landing
      page — frequently *the* canonical description), `docs/README.md`,
      `mkdocs.yml`, `pyproject.toml`, `package.json`,
      `datapackage.json`, `requirements.txt`. Each entry is the text
      content or `null` if missing.
    - `root_listing` — top-level files and directories of the repo
      (real names, not guesses). Use this to plan follow-ups: if you
      need source code, look for `src/`, `lib/`, the repo name as a
      folder, etc., and call `list_repo_contents(repo, "src")` to
      drill in. Then `get_file_content` on real paths.

    Do **not** call `convert_document` to "fetch a URL" — that tool is
    only for files uploaded by the user in the chat. To learn about a
    repo, always use this tool.

    Do **not** call `list_org_repos` when the question is about a
    single named repo — it returns all 100+ org repos and wastes
    context. Use this tool instead.

    Errors are returned as `{"ok": false, "error": "repo not found"}`
    when the repo itself is missing. Individual missing files do not
    cause an error.

    The owner is always the configured organization — pass only the
    repo name.
    """
    ctx = await get_context()
    safe = _safe_repo_name(repo)

    meta_task = asyncio.create_task(_safe_get_repo_meta(ctx, safe))
    readme_task = asyncio.create_task(_safe_get_readme(ctx, safe))
    root_task = asyncio.create_task(_safe_list_dir(ctx, safe, ""))
    aux_tasks = {
        path: asyncio.create_task(_safe_get_file(ctx, safe, path))
        for path in _DESCRIBE_REPO_AUX_FILES
    }

    metadata, readme, root_listing = await asyncio.gather(
        meta_task, readme_task, root_task
    )
    aux_results = await asyncio.gather(*aux_tasks.values())
    aux_files = {
        path: (entry["content"] if entry else None)
        for path, entry in zip(aux_tasks.keys(), aux_results)
    }

    if (
        metadata is None
        and readme is None
        and root_listing is None
        and not any(aux_files.values())
    ):
        return {"ok": False, "error": "repo not found", "repo": safe}

    return {
        "ok": True,
        "repo": safe,
        "metadata": metadata,
        "readme": readme["content"] if readme else None,
        "readme_size_bytes": readme["size_bytes"] if readme else None,
        "aux_files": aux_files,
        "aux_files_found": [p for p, c in aux_files.items() if c is not None],
        "root_listing": root_listing,
    }
