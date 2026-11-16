"""LinkedIn integration (Posts API, `w_member_social`).

https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api

Requires an access token with `w_member_social` and the author URN, e.g.
`urn:li:person:AbCdEf123`.
"""

from __future__ import annotations

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome


class LinkedInAdapter(PlatformAdapter):
    platform_id = "linkedin"
    platform_name = "LinkedIn"
    required_settings = ("LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_URN")
    #: LinkedIn shows an authwall to anonymous clients, so the public-access
    #: result is the declared visibility rather than a verified fetch.
    supports_public_check = False

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        response = await self.send(
            "POST",
            "https://api.linkedin.com/rest/posts",
            headers={
                "Authorization": f"Bearer {self.settings.linkedin_access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
                "LinkedIn-Version": str(self.settings.linkedin_version),
            },
            json={
                "author": str(self.settings.linkedin_author_urn),
                "commentary": message.text,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
        )
        post_urn = response.headers.get("x-restli-id") or response.headers.get("X-RestLi-Id")
        if not post_urn:
            raise PlatformError(
                ErrorCode.UNEXPECTED,
                "LinkedIn accepted the post but did not return an x-restli-id header.",
                http_status=response.status_code,
            )
        return PublishOutcome(
            posted_url=f"https://www.linkedin.com/feed/update/{post_urn}/",
            post_id=post_urn,
            http_status=response.status_code,
        )
