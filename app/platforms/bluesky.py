"""Bluesky / AT Protocol integration.

https://docs.bsky.app/docs/api/com-atproto-server-create-session
https://docs.bsky.app/docs/api/com-atproto-repo-create-record
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _link_facets(text: str, url: str) -> list[dict[str, Any]]:
    """AT Protocol facets use *UTF-8 byte* offsets, not character offsets."""
    index = text.find(url)
    if index < 0:
        return []
    byte_start = len(text[:index].encode("utf-8"))
    byte_end = byte_start + len(url.encode("utf-8"))
    return [
        {
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        }
    ]


class BlueskyAdapter(PlatformAdapter):
    platform_id = "bluesky"
    platform_name = "Bluesky"
    required_settings = ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        pds = self.settings.bluesky_pds_url.rstrip("/")

        session_response = await self.send(
            "POST",
            f"{pds}/xrpc/com.atproto.server.createSession",
            json={
                "identifier": self.settings.bluesky_handle,
                "password": self.settings.bluesky_app_password,
            },
        )
        session = self.json_body(session_response)
        access_jwt = session.get("accessJwt")
        did = session.get("did")
        handle = session.get("handle") or self.settings.bluesky_handle
        if not access_jwt or not did:
            raise PlatformError(
                ErrorCode.UNEXPECTED,
                "Bluesky session response did not include accessJwt/did.",
            )

        record: dict[str, Any] = {
            "text": message.text,
            "createdAt": _now_iso(),
            "langs": ["en"],
        }
        facets = _link_facets(message.text, message.url)
        if facets:
            record["facets"] = facets

        create_response = await self.send(
            "POST",
            f"{pds}/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {access_jwt}"},
            json={
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": record,
            },
        )
        created = self.json_body(create_response)
        uri = str(created.get("uri") or "")
        rkey = uri.rsplit("/", 1)[-1]
        if not rkey:
            raise PlatformError(ErrorCode.UNEXPECTED, "Bluesky did not return a post URI.")

        return PublishOutcome(
            posted_url=f"https://bsky.app/profile/{handle}/post/{rkey}",
            post_id=uri,
            http_status=create_response.status_code,
        )
