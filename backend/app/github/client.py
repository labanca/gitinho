"""GitHub HTTP client (REST + GraphQL) with org allowlist enforcement."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import Settings
from app.github.app_auth import GitHubAppAuth
from app.logging_setup import get_logger

log = get_logger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"


class OrgAllowlistError(RuntimeError):
    """Raised when a request would target an owner outside ALLOWED_ORG."""


class GitHubClient:
    def __init__(self, settings: Settings, auth: GitHubAppAuth | None = None):
        self._settings = settings
        self._auth = auth or GitHubAppAuth(settings)
        self._http = httpx.AsyncClient(
            timeout=30,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gitinho/0.1",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def org(self) -> str:
        return self._settings.ALLOWED_ORG

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

    # ── REST ─────────────────────────────────────────────────────────
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
        url = f"{GITHUB_API}{path}" if path.startswith("/") else path
        for attempt in range(4):
            headers = await self._headers()
            resp = await self._http.request(
                method, url, params=params, json=json, headers=headers
            )
            if resp.status_code == 429 or (
                resp.status_code == 403
                and resp.headers.get("x-ratelimit-remaining") == "0"
            ):
                wait = self._retry_after(resp, attempt)
                log.warning("github.rate_limited", path=path, wait_s=wait)
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 500 and attempt < 3:
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.json() if resp.content else None
        raise httpx.HTTPError(f"Failed after retries: {method} {path}")

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
            import time as _t

            try:
                return max(1.0, float(reset) - _t.time())
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
    ):
        """Async generator over REST pagination via Link header."""
        self._check_owner(owner)
        params = dict(params or {})
        params.setdefault("per_page", per_page)
        url: str | None = f"{GITHUB_API}{path}" if path.startswith("/") else path
        pages = 0
        while url and pages < max_pages:
            headers = await self._headers()
            resp = await self._http.get(url, params=params, headers=headers)
            if resp.status_code == 429 or (
                resp.status_code == 403
                and resp.headers.get("x-ratelimit-remaining") == "0"
            ):
                wait = self._retry_after(resp, pages)
                await asyncio.sleep(wait)
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

    # ── GraphQL ──────────────────────────────────────────────────────
    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        headers = await self._headers()
        for attempt in range(4):
            resp = await self._http.post(
                GITHUB_GRAPHQL,
                json={"query": query, "variables": variables or {}},
                headers=headers,
            )
            if resp.status_code >= 500 and attempt < 3:
                await asyncio.sleep(2**attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                # Retry on rate limiting
                if any(e.get("type") == "RATE_LIMITED" for e in data["errors"]):
                    await asyncio.sleep(self._retry_after(resp, attempt))
                    continue
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            return data["data"]
        raise httpx.HTTPError("Failed GraphQL after retries")
