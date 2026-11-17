"""Verify that a published URL is readable without authentication.

Most submissions hardcode `public_access: true`. This module earns the field:
it fetches the URL anonymously and looks for the usual login-wall signals.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.logging import get_logger

logger = get_logger(__name__)

_LOGIN_PATH_MARKERS = (
    "/login",
    "/signin",
    "/sign-in",
    "/authwall",
    "/checkpoint",
    "/accounts/login",
)
_LOGIN_BODY_MARKERS = (
    "sign in to continue",
    "log in to continue",
    "please log in",
    "you must be logged in",
    "join now to continue",
    "authwall",
    "enable javascript and cookies",
)
_DENIED_STATUS = frozenset({401, 403, 404, 410, 451, 999})
_MAX_BODY_SCAN = 120_000


@dataclass(frozen=True, slots=True)
class PublicCheckResult:
    public: bool | None
    verified: bool


def _looks_like_login(final_url: str, body: str) -> bool:
    path = httpx.URL(final_url).path.lower()
    if any(marker in path for marker in _LOGIN_PATH_MARKERS):
        return True
    lowered = body[:_MAX_BODY_SCAN].lower()
    return any(marker in lowered for marker in _LOGIN_BODY_MARKERS)


async def check_public_access(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout_seconds: float = 8.0,
) -> PublicCheckResult:
    """Anonymous GET. Never raises; inconclusive results return `verified=False`."""
    try:
        response = await client.get(
            url,
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"},
        )
    except httpx.HTTPError as exc:
        logger.info(
            "public_access_check_failed",
            extra={"data": {"url": url, "reason": repr(exc)}},
        )
        return PublicCheckResult(public=None, verified=False)

    if response.status_code in _DENIED_STATUS:
        return PublicCheckResult(public=False, verified=True)

    if 200 <= response.status_code < 300:
        content_type = response.headers.get("content-type", "")
        if "html" in content_type.lower():
            try:
                body = response.text
            except Exception:  # pragma: no cover - defensive
                body = ""
            if _looks_like_login(str(response.url), body):
                return PublicCheckResult(public=False, verified=True)
        return PublicCheckResult(public=True, verified=True)

    return PublicCheckResult(public=None, verified=False)
