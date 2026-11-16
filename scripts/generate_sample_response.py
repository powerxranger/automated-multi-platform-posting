"""Render an example response document from the orchestration layer.

The platform adapters are replaced with deterministic test doubles, so this
produces the exact JSON shape without touching any real API. Real captured runs
belong in `docs/sample_responses/` after credentials are configured.

    python scripts/generate_sample_response.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from tests.conftest import StubAdapter, build_settings, make_client  # noqa: E402

from app.errors import ErrorCode, PlatformError  # noqa: E402
from app.platforms.base import PublishOutcome  # noqa: E402
from app.services.posting_service import PostingService  # noqa: E402
from app.services.url_validator import parse_message  # noqa: E402

MESSAGE = (
    "Check out our latest business platform and grow your online visibility. https://example.com"
)

# (id, display name, posted url, simulated latency, anonymously checkable)
PLATFORMS = [
    (
        "bluesky",
        "Bluesky",
        "https://bsky.app/profile/demo.bsky.social/post/3kexample",
        0.21,
        True,
    ),
    (
        "mastodon",
        "Mastodon",
        "https://mastodon.social/@demo/113000000000000001",
        0.28,
        True,
    ),
    ("telegram", "Telegram", "https://t.me/demo_channel/42", 0.16, True),
    (
        "devto",
        "Dev.to",
        "https://dev.to/demo/grow-your-online-visibility-3f1a",
        0.41,
        True,
    ),
    (
        "gist",
        "GitHub Gist",
        "https://gist.github.com/demo/0123456789abcdef",
        0.19,
        True,
    ),
    (
        "linkedin",
        "LinkedIn",
        "https://www.linkedin.com/feed/update/urn:li:share:7123456789/",
        0.33,
        False,
    ),
]


async def build_document() -> dict[str, object]:
    settings = build_settings(public_check_enabled=True, app_timezone="Asia/Kolkata")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                text="<html><body>Post</body></html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(201, json={"ok": True})

    client = make_client(handler)
    adapters: list[StubAdapter] = []

    for platform_id, name, url, latency, checkable in PLATFORMS:
        adapters.append(
            StubAdapter(
                settings,
                client,
                platform_id=platform_id,
                platform_name=name,
                delay=latency,
                supports_public_check=checkable,
                outcome=PublishOutcome(posted_url=url, post_id=platform_id, http_status=201),
            )
        )

    # One deliberate failure to demonstrate error isolation.
    adapters.append(
        StubAdapter(
            settings,
            client,
            platform_id="x",
            platform_name="X (Twitter)",
            delay=0.12,
            errors=[PlatformError(ErrorCode.AUTH_FAILED, "Authentication failed")],
        )
    )

    service = PostingService(settings, adapters, client)
    response = await service.publish(parse_message(MESSAGE), idempotency_key=None)
    document = response.model_dump()
    document["request_id"] = "0f9c2f0f4b6a4d7e9c1a2b3c4d5e6f70"
    return document


def main() -> None:
    document = asyncio.run(build_document())
    target = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "sample_responses"
        / "illustrative-response.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
