"""GitHub HTTP client (REST + GraphQL) with org allowlist enforcement."""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator

import httpx

from gitinho_mcp.config import Settings
from gitinho_mcp.github.app_auth import GitHubAppAuth


class OrgAllowlistError(RuntimeError):
    """Raised when a request would target an owner outside ALLOWED_ORG."""


class GitHubAuthRejected(RuntimeError):
    """Raised when GitHub returns 401 for an authenticated request.

    Gitinho authenticates as a GitHub App installation (NOT a user PAT), so
    this almost never means the operator needs to rotate a personal token.
    The two real causes are:
      - GitHub abuse-protection (often follows 5xx storms on heavy queries)
      - the App installation having been revoked/removed on the org side
    The error message spells this out so the chat agent doesn't suggest the
    user fix a PAT that doesn't exist in this architecture.
    """

    @classmethod
    def for_endpoint(cls, endpoint: str, saw_5xx: bool) -> GitHubAuthRejected:
        cause = (
            "likely GitHub abuse-protection — heavy/expensive queries can "
            "trigger a 401 after the server times out (5xx). Retry in a "
            "few seconds, and reduce query weight if it persists."
            if saw_5xx
            else "the App installation token was rejected. Verify the "
            "GitHub App is still installed on the org with the required "
            "permissions; this is NOT a user-fixable PAT issue."
        )
        return cls(f"GitHub {endpoint} 401 Unauthorized — {cause}")


class GitHubClient:
    def __init__(self, settings: Settings, auth: GitHubAppAuth | None = None) -> None:
        self._settings = settings
        self._auth = auth or GitHubAppAuth(settings)
        self._http = httpx.AsyncClient(
            timeout=30,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gitinho-mcp/0.2",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def org(self) -> str:
        return self._settings.ALLOWED_ORG

    @property
    def api_base(self) -> str:
        return self._settings.GITHUB_API_BASE

    @property
    def graphql_url(self) -> str:
        return self._settings.GITHUB_GRAPHQL_URL

    def _check_owner(self, owner: str | None) -> None:
        if owner is None:
            return
        if owner.lower() != self.org:
            raise OrgAllowlistError(
                f"Owner '{owner}' is not in the allowlist (allowed: {self.org})"
            )

    async def _headers(self) -> dict[str, str]:
        token = await self._auth.installation_token()
        return {"Authorization": f"Bearer {token}"}

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        owner: str | None = None,
    ) -> dict | list:
        self._check_owner(owner)
        return await self._request("GET", path, params=params)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        url = f"{self.api_base}{path}" if path.startswith("/") else path
        saw_5xx = False
        retried_fresh_token = False
        for attempt in range(4):
            headers = await self._headers()
            resp = await self._http.request(
                method, url, params=params, json=json, headers=headers
            )
            if self._is_rate_limited(resp):
                await asyncio.sleep(self._retry_after(resp, attempt))
                continue
            if resp.status_code >= 500 and attempt < 3:
                saw_5xx = True
                await asyncio.sleep(2**attempt)
                continue
            if resp.status_code == 401 and not retried_fresh_token:
                # GitHub abuse-protection sometimes blacklists a specific
                # installation token after a 5xx storm — minting a fresh
                # token usually clears it.
                self._auth.evict_cached_token()
                retried_fresh_token = True
                await asyncio.sleep(2)
                continue
            if resp.status_code == 401:
                raise GitHubAuthRejected.for_endpoint(
                    f"REST {method} {path}", saw_5xx
                )
            resp.raise_for_status()
            return resp.json() if resp.content else None
        raise httpx.HTTPError(f"Failed after retries: {method} {path}")

    @staticmethod
    def _is_rate_limited(resp: httpx.Response) -> bool:
        return resp.status_code == 429 or (
            resp.status_code == 403
            and resp.headers.get("x-ratelimit-remaining") == "0"
        )

    @staticmethod
    def _retry_after(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        reset = resp.headers.get("x-ratelimit-reset")
        if reset:
            try:
                return max(1.0, float(reset) - time.time())
            except ValueError:
                pass
        return min(60.0, 2**attempt)

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        owner: str | None = None,
        per_page: int = 100,
        max_pages: int = 100,
    ) -> AsyncIterator[Any]:
        self._check_owner(owner)
        params = dict(params or {})
        params.setdefault("per_page", per_page)
        url: str | None = f"{self.api_base}{path}" if path.startswith("/") else path
        pages = 0
        while url and pages < max_pages:
            headers = await self._headers()
            resp = await self._http.get(url, params=params, headers=headers)
            if self._is_rate_limited(resp):
                await asyncio.sleep(self._retry_after(resp, pages))
                continue
            resp.raise_for_status()
            body = resp.json()
            if isinstance(body, list):
                for item in body:
                    yield item
            else:
                yield body
            params = None
            url = self._next_url(resp)
            pages += 1

    @staticmethod
    def _next_url(resp: httpx.Response) -> str | None:
        link = resp.headers.get("link")
        if not link:
            return None
        for part in link.split(","):
            section = part.strip().split(";")
            if len(section) < 2:
                continue
            url_part, rel_part = section[0], section[1]
            if 'rel="next"' in rel_part:
                return url_part.strip().lstrip("<").rstrip(">")
        return None

    async def graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict:
        saw_5xx = False
        retried_fresh_token = False
        for attempt in range(4):
            headers = await self._headers()
            resp = await self._http.post(
                self.graphql_url,
                json={"query": query, "variables": variables or {}},
                headers=headers,
            )
            if resp.status_code >= 500 and attempt < 3:
                saw_5xx = True
                await asyncio.sleep(2**attempt)
                continue
            if resp.status_code == 401 and not retried_fresh_token:
                # GitHub abuse-protection sometimes blacklists a specific
                # installation token after a 5xx storm — minting a fresh
                # token usually clears it.
                self._auth.evict_cached_token()
                retried_fresh_token = True
                await asyncio.sleep(2)
                continue
            if resp.status_code == 401:
                raise GitHubAuthRejected.for_endpoint("GraphQL", saw_5xx)
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                if any(e.get("type") == "RATE_LIMITED" for e in data["errors"]):
                    await asyncio.sleep(self._retry_after(resp, attempt))
                    continue
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            return data["data"]
        raise httpx.HTTPError("Failed GraphQL after retries")
