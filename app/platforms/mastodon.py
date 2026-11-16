"""Mastodon integration (POST /api/v1/statuses).

https://docs.joinmastodon.org/methods/statuses/#create
"""

from __future__ import annotations

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome


class MastodonAdapter(PlatformAdapter):
    platform_id = "mastodon"
    platform_name = "Mastodon"
    required_settings = ("MASTODON_INSTANCE_URL", "MASTODON_ACCESS_TOKEN")

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        instance = str(self.settings.mastodon_instance_url or "").rstrip("/")
        if not instance.startswith(("http://", "https://")):
            instance = f"https://{instance}"

        response = await self.send(
            "POST",
            f"{instance}/api/v1/statuses",
            headers={"Authorization": f"Bearer {self.settings.mastodon_access_token}"},
            json={
                "status": message.text,
                "visibility": self.settings.mastodon_visibility,
                "language": "en",
            },
        )
        body = self.json_body(response)
        posted_url = body.get("url") or body.get("uri")
        if not posted_url:
            raise PlatformError(ErrorCode.UNEXPECTED, "Mastodon did not return a status URL.")
        return PublishOutcome(
            posted_url=str(posted_url),
            post_id=str(body.get("id") or "") or None,
            http_status=response.status_code,
        )
