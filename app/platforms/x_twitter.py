"""X (Twitter) integration (POST /2/tweets with OAuth 1.0a user context).

https://docs.x.com/x-api/posts/creation-of-a-post
"""

from __future__ import annotations

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome
from app.platforms.oauth1 import oauth1_header


class XAdapter(PlatformAdapter):
    platform_id = "x"
    platform_name = "X (Twitter)"
    required_settings = (
        "X_API_KEY",
        "X_API_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
    )
    #: X serves an authwall/JS shell to anonymous clients.
    supports_public_check = False

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        url = "https://api.x.com/2/tweets"
        auth_header = oauth1_header(
            "POST",
            url,
            consumer_key=str(self.settings.x_api_key),
            consumer_secret=str(self.settings.x_api_secret),
            token=str(self.settings.x_access_token),
            token_secret=str(self.settings.x_access_token_secret),
        )
        response = await self.send(
            "POST",
            url,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            json={"text": message.text},
        )
        body = self.json_body(response)
        data = body.get("data") or {}
        tweet_id = data.get("id")
        if not tweet_id:
            raise PlatformError(ErrorCode.UNEXPECTED, "X did not return the created post id.")
        return PublishOutcome(
            posted_url=f"https://x.com/i/web/status/{tweet_id}",
            post_id=str(tweet_id),
            http_status=response.status_code,
        )
