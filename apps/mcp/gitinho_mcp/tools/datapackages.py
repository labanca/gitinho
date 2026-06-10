"""Flat inventory of Frictionless datapackage resources across the org.

`find_datapackages` answers "which repos have a `datapackage.json`?".
This module answers the next question — "what resources do all those
datapackages contain?" — in one tool call, so the agent doesn't have to
chain N `get_file_content` calls and reassemble the flat list by hand
(a step where rows can silently get dropped under context pressure).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import yaml

from gitinho_mcp.server import mcp
from gitinho_mcp.tools._context import ToolContext, get_context
from gitinho_mcp.tools.repos import (
    _decode_content_payload,
    discover_datapackage_repos,
)


def _parse_manifest(text: str, manifest_path: str) -> dict[str, Any]:
    """Parse manifest text as JSON or YAML based on filename. Returns parsed
    dict on success, or raises ValueError with a human-readable reason."""
    if manifest_path.endswith(".json"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
    else:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("manifest is not a mapping/object")
    return parsed


async def _fetch_manifest(
    ctx: ToolContext,
    repo_short: str,
    manifest_path: str,
    sem: asyncio.Semaphore,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Return (repo_short, parsed_manifest, error_message)."""
    async with sem:
        try:
            data = await ctx.gh.get(
                f"/repos/{ctx.org}/{repo_short}/contents/{manifest_path}",
                owner=ctx.org,
            )
        except httpx.HTTPStatusError as exc:
            return repo_short, None, f"HTTP {exc.response.status_code}"
        if not isinstance(data, dict):
            return repo_short, None, "unexpected response shape"
        decoded = _decode_content_payload(data, ref=None)
        if not decoded.get("ok"):
            return repo_short, None, str(decoded.get("error") or "decode failed")
        try:
            manifest = _parse_manifest(decoded["content"], manifest_path)
        except ValueError as exc:
            return repo_short, None, str(exc)
        return repo_short, manifest, None


def _resource_row(repo_full: str, repo_url: str, resource: Any) -> dict[str, Any]:
    if not isinstance(resource, dict):
        return {
            "repo": repo_full,
            "repo_url": repo_url,
            "resource_name": None,
            "format": None,
            "path": None,
            "schema_fields_count": None,
            "mediatype": None,
            "encoding": None,
            "bytes": None,
            "_raw_preview": str(resource)[:200],
        }
    schema = resource.get("schema")
    fields_count: int | None = None
    if isinstance(schema, dict):
        fields = schema.get("fields")
        if isinstance(fields, list):
            fields_count = len(fields)
    return {
        "repo": repo_full,
        "repo_url": repo_url,
        "resource_name": resource.get("name"),
        "format": resource.get("format"),
        "path": resource.get("path"),
        "schema_fields_count": fields_count,
        "mediatype": resource.get("mediatype"),
        "encoding": resource.get("encoding"),
        "bytes": resource.get("bytes"),
    }


@mcp.tool()
async def list_datapackage_resources(
    include_archived: bool = False,
    repo: str | None = None,
) -> dict[str, Any]:
    """Flat inventory of every Frictionless `resources[]` entry across the org.

    One row per (repo, resource). Discovers datapackages via the same
    GraphQL query as `find_datapackages`, then fetches each
    `datapackage.json` and flattens its `resources[]` into a single list.

    **Use this** for any request like "todos os recursos de todos os
    datapackages", "inventário extensivo de recursos", "lista completa de
    recursos por repo" — it returns the authoritative flat list in one
    call so you can pass it verbatim to `createTable` without manually
    assembling the rows (which is where items can get dropped).

    Pass `repo` (name only, no owner) to scope to a single repository.

    Returns `{criterion, org, total_repos, total_resources, rows, errors}`.
    `errors` lists repos whose manifest was unreadable or malformed —
    surface them to the user, don't silently skip.
    """
    ctx = await get_context()

    nodes = await discover_datapackage_repos(
        ctx, include_archived=include_archived, repo_filter=repo
    )
    candidates: list[tuple[str, str, str]] = [
        (n["nameWithOwner"], n["url"], n["manifest_path"]) for n in nodes
    ]

    sem = asyncio.Semaphore(10)
    results = await asyncio.gather(
        *[
            _fetch_manifest(
                ctx, full_name.split("/", 1)[-1], manifest_path, sem
            )
            for full_name, _, manifest_path in candidates
        ]
    )

    by_short = {
        full_name.split("/", 1)[-1]: (full_name, url, manifest_path)
        for full_name, url, manifest_path in candidates
    }
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for repo_short, manifest, err in results:
        full_name, repo_url, _ = by_short[repo_short]
        if err is not None or manifest is None:
            errors.append({"repo": full_name, "reason": err or "no manifest"})
            continue
        resources = manifest.get("resources")
        if not isinstance(resources, list):
            errors.append({"repo": full_name, "reason": "no `resources` list"})
            continue
        for r in resources:
            rows.append(_resource_row(full_name, repo_url, r))

    rows.sort(
        key=lambda x: (x.get("repo") or "", x.get("resource_name") or "")
    )
    return {
        "criterion": (
            "Frictionless resources[] in datapackage.json/.yaml/.yml at "
            "repo root (JSON preferred)"
        ),
        "source": "GraphQL discovery + REST /contents/<manifest> per repo",
        "org": ctx.org,
        "total_repos": len(candidates),
        "total_resources": len(rows),
        "include_archived": include_archived,
        "rows": rows,
        "errors": errors,
    }
