"""Smoke test — exercise a handful of MCP tools end-to-end against splor-mg.

Picks one tool from each new module (commits, discussions, issues, pulls,
users, activity, repos) to verify the GitHub App auth + GraphQL/REST paths
all work after Phase 3.
"""

from __future__ import annotations

import asyncio
import json

from gitinho_mcp import tools  # noqa: F401 — registers tools
from gitinho_mcp.tools._context import aclose, get_context


async def main() -> None:
    ctx = await get_context()
    print(f"Allowed org: {ctx.org}\n")

    from gitinho_mcp.tools.issues import count_open_issues
    from gitinho_mcp.tools.repos import (
        count_repos,
        describe_repo,
        get_file_content,
        get_repo_readme,
        list_repo_contents,
        repos_with_multiple_branches,
    )
    from gitinho_mcp.tools.users import list_org_members

    try:
        repo_counts = await count_repos()
        print("count_repos:", json.dumps(repo_counts, indent=2))

        open_issues = await count_open_issues()
        print(
            f"\ncount_open_issues: total={open_issues['total_open_issues']}, "
            f"repos with open issues={len(open_issues['per_repo'])}"
        )

        multi = await repos_with_multiple_branches()
        print(
            f"\nrepos_with_multiple_branches: count={multi['count']} "
            f"(top 3): {[r['name'] for r in multi['repos'][:3]]}"
        )

        members = await list_org_members()
        print(f"\nlist_org_members: total={members['total']}")

        readme = await get_repo_readme("gitinho")
        if readme.get("ok"):
            preview = readme["content"][:120].replace("\n", " ")
            print(
                f"\nget_repo_readme(gitinho): ok size={readme['size_bytes']}B "
                f"preview={preview!r}"
            )
        else:
            print(f"\nget_repo_readme(gitinho): FAIL {readme}")

        pyproject = await get_file_content("gitinho", "pyproject.toml")
        if pyproject.get("ok"):
            print(
                f"\nget_file_content(gitinho, pyproject.toml): ok "
                f"size={pyproject['size_bytes']}B"
            )
        else:
            print(
                f"\nget_file_content(gitinho, pyproject.toml): FAIL {pyproject}"
            )

        missing = await get_file_content("gitinho", "does-not-exist.txt")
        print(f"\nget_file_content(missing file): {missing}")

        described = await describe_repo("dpm")
        if described.get("ok"):
            meta = described.get("metadata") or {}
            root = described.get("root_listing") or []
            print(
                f"\ndescribe_repo(dpm): ok lang={meta.get('language')} "
                f"readme={described.get('readme_size_bytes')}B "
                f"aux_found={described.get('aux_files_found')} "
                f"root_entries={len(root)}"
            )
        else:
            print(f"\ndescribe_repo(dpm): FAIL {described}")

        listing = await list_repo_contents("dpm", "src")
        if listing.get("ok"):
            print(
                f"\nlist_repo_contents(dpm, src): ok total={listing['total']} "
                f"sample={[e['name'] for e in listing['entries'][:5]]}"
            )
        else:
            print(f"\nlist_repo_contents(dpm, src): {listing}")
    finally:
        await aclose()


if __name__ == "__main__":
    asyncio.run(main())
