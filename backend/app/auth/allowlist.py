"""Check GitHub org membership for the OAuth-authenticated user."""

from __future__ import annotations

import httpx

GITHUB_API = "https://api.github.com"


async def is_member_of_org(user_token: str, org: str) -> bool:
    """Return True iff the user with the OAuth token is a member of `org`.

    Uses GET /user/memberships/orgs/{org} which works for both public and
    private members (the user is authenticated with their own token).
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{GITHUB_API}/user/memberships/orgs/{org}",
            headers={
                "Authorization": f"Bearer {user_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code == 200:
        data = resp.json()
        return data.get("state") == "active"
    return False
