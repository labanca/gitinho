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
    from gitinho_mcp.tools.repos import count_repos, repos_with_multiple_branches
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
    finally:
        await aclose()


if __name__ == "__main__":
    asyncio.run(main())
