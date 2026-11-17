"""Dev.to (Forem) integration (POST /api/articles).

https://developers.forem.com/api/v1#tag/articles/operation/createArticle

Dev.to's create endpoint can return a URL for an article that is still a
draft. We check the article after creating it, force-publish when needed, and
only return a URL that is publicly readable.
"""

from __future__ import annotations

import asyncio

import httpx

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

    async def _article(self, article_id: str | int, headers: dict[str, str]) -> dict[str, object]:
        response = await self.send(
            "GET", f"https://dev.to/api/articles/{article_id}", headers=headers
        )
        return dict(self.json_body(response))

    async def _wait_until_public(self, url: str) -> None:
        """A created article is not a success until the URL actually loads."""
        last_status: int | None = None
        for attempt in range(3):
            try:
                response = await self.client.get(
                    url,
                    follow_redirects=True,
                    timeout=2.0,
                    headers={"Accept": "text/html"},
                )
                last_status = response.status_code
                if 200 <= response.status_code < 300:
                    body = response.text[:2000].lower()
                    if "page not found" not in body:
                        return
            except httpx.HTTPError:
                last_status = None
            if attempt < 2:
                await asyncio.sleep(0.25)

        raise PlatformError(
            ErrorCode.UNEXPECTED,
            f"Dev.to created the article but it is not publicly readable "
            f"(last HTTP status: {last_status}).",
        )

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        headers = {"api-key": str(self.settings.devto_api_key)}
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
            headers=headers,
            json={"article": article},
        )
        created = self.json_body(response)
        article_id = created.get("id")
        if not article_id:
            raise PlatformError(ErrorCode.UNEXPECTED, "Dev.to did not return an article id.")

        final_url = str(created.get("url") or created.get("canonical_url") or "")

        # DEV.to sometimes saves a `published: true` create as a draft. The
        # POST response still looks successful, so verify the side effect.
        saved = await self._article(article_id, headers)
        final_url = str(saved.get("url") or final_url)
        if saved.get("published") is False:
            await self.send(
                "PUT",
                f"https://dev.to/api/articles/{article_id}",
                headers=headers,
                json={"article": {"published": True}},
            )
            for _ in range(3):
                saved = await self._article(article_id, headers)
                final_url = str(saved.get("url") or final_url)
                if saved.get("published") is True:
                    break
                await asyncio.sleep(0.25)

        if not final_url:
            raise PlatformError(ErrorCode.UNEXPECTED, "Dev.to did not return an article URL.")

        await self._wait_until_public(final_url)

        return PublishOutcome(
            posted_url=final_url,
            post_id=str(article_id),
            http_status=response.status_code,
        )
