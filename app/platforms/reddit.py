"""Reddit integration (OAuth2 password grant + /api/submit).

https://www.reddit.com/dev/api/#POST_api_submit

Note: young accounts are frequently auto-removed by subreddit spam filters. Use
an established account and a subreddit whose rules allow link posts.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import httpx

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SUBMIT_URL = "https://oauth.reddit.com/api/submit"


class RedditAdapter(PlatformAdapter):
    platform_id = "reddit"
    platform_name = "Reddit"
    required_settings = (
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USERNAME",
        "REDDIT_PASSWORD",
        "REDDIT_SUBREDDIT",
    )

    def __init__(self, settings: Any, client: httpx.AsyncClient) -> None:
        super().__init__(settings, client)
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        response = await self.send(
            "POST",
            _TOKEN_URL,
            headers={"User-Agent": self.settings.reddit_user_agent},
            auth=httpx.BasicAuth(
                str(self.settings.reddit_client_id),
                str(self.settings.reddit_client_secret),
            ),
            data={
                "grant_type": "password",
                "username": str(self.settings.reddit_username),
                "password": str(self.settings.reddit_password),
            },
        )
        body = self.json_body(response)
        token = body.get("access_token")
        if not token:
            raise PlatformError(
                ErrorCode.AUTH_FAILED,
                f"Reddit did not return an access token: {body.get('error', 'unknown')}",
                http_status=response.status_code,
            )
        self._token = str(token)
        # Refresh a minute early to avoid edge-of-expiry failures.
        expires_in = float(body.get("expires_in") or 3600)
        self._token_expires_at = time.monotonic() + max(expires_in - 60, 30)
        return self._token

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        token = await self._access_token()
        subreddit = str(self.settings.reddit_subreddit).lstrip("r/")

        response = await self.send(
            "POST",
            _SUBMIT_URL,
            headers={
                "Authorization": f"bearer {token}",
                "User-Agent": self.settings.reddit_user_agent,
            },
            data={
                "api_type": "json",
                "kind": "link",
                "sr": subreddit,
                "title": message.title,
                "url": message.url,
                "resubmit": "false",
            },
        )
        body = self.json_body(response)
        payload: Mapping[str, Any] = body.get("json") or {}
        errors = payload.get("errors") or []
        if errors:
            raise PlatformError(
                ErrorCode.PLATFORM_REJECTED,
                f"Reddit rejected the post: {errors}",
                http_status=response.status_code,
            )
        data = payload.get("data") or {}
        posted_url = data.get("url")
        if not posted_url:
            raise PlatformError(
                ErrorCode.UNEXPECTED, "Reddit did not return the submitted post URL."
            )
        return PublishOutcome(
            posted_url=str(posted_url),
            post_id=str(data.get("name") or data.get("id") or "") or None,
            http_status=response.status_code,
        )
