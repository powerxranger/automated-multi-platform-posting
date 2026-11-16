"""Hashnode integration (GraphQL `publishPost` mutation).

https://apidocs.hashnode.com/#mutation-publishPost
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome

_ENDPOINT = "https://gql.hashnode.com/"
_MUTATION = """
mutation PublishPost($input: PublishPostInput!) {
  publishPost(input: $input) {
    post {
      id
      url
      slug
    }
  }
}
"""


class HashnodeAdapter(PlatformAdapter):
    platform_id = "hashnode"
    platform_name = "Hashnode"
    required_settings = ("HASHNODE_TOKEN", "HASHNODE_PUBLICATION_ID")

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        response = await self.send(
            "POST",
            _ENDPOINT,
            headers={"Authorization": f"Bearer {self.settings.hashnode_token}"},
            json={
                "query": _MUTATION,
                "variables": {
                    "input": {
                        "title": message.title,
                        "publicationId": str(self.settings.hashnode_publication_id),
                        "contentMarkdown": message.text,
                        "tags": [],
                    }
                },
            },
        )
        body = self.json_body(response)
        if body.get("errors"):
            raise PlatformError(
                ErrorCode.PLATFORM_REJECTED,
                f"Hashnode rejected the post: {body['errors']}",
                http_status=response.status_code,
            )
        data: Mapping[str, Any] = body.get("data") or {}
        post = (data.get("publishPost") or {}).get("post") or {}
        posted_url = post.get("url")
        if not posted_url:
            raise PlatformError(ErrorCode.UNEXPECTED, "Hashnode did not return a post URL.")
        return PublishOutcome(
            posted_url=str(posted_url),
            post_id=str(post.get("id") or "") or None,
            http_status=response.status_code,
        )
