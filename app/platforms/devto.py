"""Dev.to (Forem) integration (POST /api/articles).

https://developers.forem.com/api/v1#tag/articles/operation/createArticle
"""

from __future__ import annotations

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome


class DevToAdapter(PlatformAdapter):
    platform_id = "devto"
    platform_name = "Dev.to"
    required_settings = ("DEVTO_API_KEY",)

    def is_configured(self) -> bool:
        return not self.missing_settings()

    def _tags(self) -> list[str]:
        raw = (self.settings.devto_tags or "").replace(";", ",")
        return [tag.strip() for tag in raw.split(",") if tag.strip()][:4]

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        article: dict[str, object] = {
            "title": message.title,
            "published": True,
            "body_markdown": message.text,
            "canonical_url": message.url,
        }
        tags = self._tags()
        if tags:
            article["tags"] = tags

        response = await self.send(
            "POST",
            "https://dev.to/api/articles",
            headers={"api-key": str(self.settings.devto_api_key)},
            json={"article": article},
        )
        body = self.json_body(response)
        posted_url = body.get("url") or body.get("canonical_url")
        if not posted_url:
            raise PlatformError(ErrorCode.UNEXPECTED, "Dev.to did not return an article URL.")
        return PublishOutcome(
            posted_url=str(posted_url),
            post_id=str(body.get("id") or "") or None,
            http_status=response.status_code,
        )
