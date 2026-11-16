"""Adapter-level tests: payload shape, URL construction, error mapping."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.config import Settings
from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage
from app.platforms.bluesky import BlueskyAdapter
from app.platforms.devto import DevToAdapter
from app.platforms.github_gist import GitHubGistAdapter
from app.platforms.hashnode import HashnodeAdapter
from app.platforms.linkedin import LinkedInAdapter
from app.platforms.mastodon import MastodonAdapter
from app.platforms.reddit import RedditAdapter
from app.platforms.telegram import TelegramAdapter
from app.platforms.x_twitter import XAdapter
from tests.conftest import make_client


def recording(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def wrapper(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return make_client(wrapper), calls


# --------------------------------------------------------------------- bluesky --


async def test_bluesky_publishes_with_utf8_link_facets(
    settings: Settings, message: ParsedMessage
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("createSession"):
            return httpx.Response(
                200,
                json={
                    "accessJwt": "jwt-token",
                    "did": "did:plc:abc123",
                    "handle": "tester.bsky.social",
                },
            )
        return httpx.Response(
            200,
            json={"uri": "at://did:plc:abc123/app.bsky.feed.post/3kxyz", "cid": "bafy"},
        )

    client, calls = recording(handler)
    outcome = await BlueskyAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://bsky.app/profile/tester.bsky.social/post/3kxyz"
    record_request = calls[1]
    assert record_request.headers["authorization"] == "Bearer jwt-token"

    import json

    body = json.loads(record_request.content)
    assert body["collection"] == "app.bsky.feed.post"
    facet = body["record"]["facets"][0]
    expected_start = len(message.text[: message.text.index(message.url)].encode("utf-8"))
    assert facet["index"]["byteStart"] == expected_start
    assert facet["index"]["byteEnd"] == expected_start + len(message.url.encode("utf-8"))
    assert facet["features"][0]["uri"] == message.url


async def test_bluesky_missing_session_token_is_an_error(
    settings: Settings, message: ParsedMessage
) -> None:
    client = make_client(lambda request: httpx.Response(200, json={"did": "x"}))
    with pytest.raises(PlatformError) as caught:
        await BlueskyAdapter(settings, client).publish_once(message)
    assert caught.value.code is ErrorCode.UNEXPECTED


# -------------------------------------------------------------------- mastodon --


async def test_mastodon_posts_public_status(settings: Settings, message: ParsedMessage) -> None:
    client, calls = recording(
        lambda request: httpx.Response(
            200, json={"id": "113", "url": "https://mastodon.test/@tester/113"}
        )
    )
    outcome = await MastodonAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://mastodon.test/@tester/113"
    assert calls[0].headers["authorization"].startswith("Bearer ")
    import json

    assert json.loads(calls[0].content)["visibility"] == "public"


# -------------------------------------------------------------------- telegram --


async def test_telegram_builds_public_channel_link(
    settings: Settings, message: ParsedMessage
) -> None:
    client, calls = recording(
        lambda request: httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})
    )
    outcome = await TelegramAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://t.me/testchannel/77"
    import json

    body = json.loads(calls[0].content)
    assert body["chat_id"] == "@testchannel"
    assert body["disable_web_page_preview"] is False


async def test_telegram_ok_false_is_a_rejection(settings: Settings, message: ParsedMessage) -> None:
    client = make_client(
        lambda request: httpx.Response(200, json={"ok": False, "description": "chat not found"})
    )
    with pytest.raises(PlatformError) as caught:
        await TelegramAdapter(settings, client).publish_once(message)
    assert caught.value.code is ErrorCode.PLATFORM_REJECTED
    assert "chat not found" in caught.value.message


# ----------------------------------------------------------------------- devto --


async def test_devto_sends_title_and_canonical_url(
    settings: Settings, message: ParsedMessage
) -> None:
    client, calls = recording(
        lambda request: httpx.Response(201, json={"id": 1, "url": "https://dev.to/tester/post-abc"})
    )
    outcome = await DevToAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://dev.to/tester/post-abc"
    import json

    article = json.loads(calls[0].content)["article"]
    assert article["canonical_url"] == message.url
    assert article["title"] == message.title
    assert article["published"] is True


# ------------------------------------------------------------------------ gist --


async def test_gist_creates_public_gist(settings: Settings, message: ParsedMessage) -> None:
    client, calls = recording(
        lambda request: httpx.Response(
            201, json={"id": "abc", "html_url": "https://gist.github.com/tester/abc"}
        )
    )
    outcome = await GitHubGistAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://gist.github.com/tester/abc"
    import json

    body = json.loads(calls[0].content)
    assert body["public"] is True
    assert "post.md" in body["files"]


# -------------------------------------------------------------------- linkedin --


async def test_linkedin_uses_restli_id_header(settings: Settings, message: ParsedMessage) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1234567890"})

    client, calls = recording(handler)
    outcome = await LinkedInAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://www.linkedin.com/feed/update/urn:li:share:1234567890/"
    assert calls[0].headers["linkedin-version"] == settings.linkedin_version
    import json

    assert json.loads(calls[0].content)["visibility"] == "PUBLIC"


async def test_linkedin_missing_restli_id_is_an_error(
    settings: Settings, message: ParsedMessage
) -> None:
    client = make_client(lambda request: httpx.Response(201))
    with pytest.raises(PlatformError) as caught:
        await LinkedInAdapter(settings, client).publish_once(message)
    assert caught.value.code is ErrorCode.UNEXPECTED


# --------------------------------------------------------------------------- x --


async def test_x_signs_the_request_with_oauth1(settings: Settings, message: ParsedMessage) -> None:
    client, calls = recording(
        lambda request: httpx.Response(201, json={"data": {"id": "1900000000", "text": "hi"}})
    )
    outcome = await XAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://x.com/i/web/status/1900000000"
    authorization = calls[0].headers["authorization"]
    assert authorization.startswith("OAuth ")
    assert "oauth_signature=" in authorization
    assert 'oauth_signature_method="HMAC-SHA1"' in authorization


# ---------------------------------------------------------------------- reddit --


async def test_reddit_fetches_token_then_submits(
    settings: Settings, message: ParsedMessage
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "access_token" in request.url.path:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={"json": {"errors": [], "data": {"url": "https://reddit.com/r/test/comments/x"}}},
        )

    client, calls = recording(handler)
    adapter = RedditAdapter(settings, client)
    outcome = await adapter.publish_once(message)

    assert outcome.posted_url == "https://reddit.com/r/test/comments/x"
    assert calls[1].headers["authorization"] == "bearer tok"
    # The token is cached for the next publish.
    await adapter.publish_once(message)
    token_calls = [c for c in calls if "access_token" in c.url.path]
    assert len(token_calls) == 1


async def test_reddit_reports_submission_errors(settings: Settings, message: ParsedMessage) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "access_token" in request.url.path:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200, json={"json": {"errors": [["SUBREDDIT_NOTALLOWED", "nope", "sr"]]}}
        )

    client = make_client(handler)
    with pytest.raises(PlatformError) as caught:
        await RedditAdapter(settings, client).publish_once(message)
    assert caught.value.code is ErrorCode.PLATFORM_REJECTED


# -------------------------------------------------------------------- hashnode --


async def test_hashnode_publishes_via_graphql(settings: Settings, message: ParsedMessage) -> None:
    client, calls = recording(
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "publishPost": {"post": {"id": "p1", "url": "https://blog.hashnode.dev/post"}}
                }
            },
        )
    )
    outcome = await HashnodeAdapter(settings, client).publish_once(message)

    assert outcome.posted_url == "https://blog.hashnode.dev/post"
    import json

    body = json.loads(calls[0].content)
    assert "publishPost" in body["query"]
    assert body["variables"]["input"]["publicationId"] == "publication-id"


# --------------------------------------------------------------- error mapping --


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, ErrorCode.AUTH_FAILED),
        (403, ErrorCode.AUTH_FAILED),
        (422, ErrorCode.PLATFORM_REJECTED),
        (404, ErrorCode.PLATFORM_REJECTED),
        (500, ErrorCode.NETWORK),
        (503, ErrorCode.NETWORK),
    ],
)
async def test_http_errors_are_mapped(
    settings: Settings,
    message: ParsedMessage,
    status_code: int,
    expected: ErrorCode,
) -> None:
    client = make_client(lambda request: httpx.Response(status_code, text="nope"))
    with pytest.raises(PlatformError) as caught:
        await MastodonAdapter(settings, client).publish_once(message)
    assert caught.value.code is expected


async def test_rate_limit_is_retryable(settings: Settings, message: ParsedMessage) -> None:
    client = make_client(
        lambda request: httpx.Response(429, headers={"retry-after": "1"}, text="slow down")
    )
    with pytest.raises(PlatformError) as caught:
        await MastodonAdapter(settings, client).publish_once(message)
    assert caught.value.code is ErrorCode.RATE_LIMITED
    assert caught.value.retryable is True
    assert caught.value.retry_after == 1.0


async def test_network_timeout_is_retryable(settings: Settings, message: ParsedMessage) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    client = make_client(handler)
    with pytest.raises(PlatformError) as caught:
        await MastodonAdapter(settings, client).publish_once(message)
    assert caught.value.code is ErrorCode.TIMEOUT
    assert caught.value.retryable is True


async def test_non_json_response_is_unexpected(settings: Settings, message: ParsedMessage) -> None:
    client = make_client(lambda request: httpx.Response(200, text="<html>hi</html>"))
    with pytest.raises(PlatformError) as caught:
        await MastodonAdapter(settings, client).publish_once(message)
    assert caught.value.code is ErrorCode.UNEXPECTED


# ------------------------------------------------------------------ readiness --


def test_adapters_report_missing_credentials(settings: Settings) -> None:
    bare = Settings(_env_file=None, bluesky_handle="", bluesky_app_password="")
    client = make_client(lambda request: httpx.Response(200, json={}))
    adapter = BlueskyAdapter(bare, client)
    assert adapter.is_configured() is False
    assert adapter.missing_settings() == ["BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"]


def test_adapters_are_configured_with_full_settings(
    settings: Settings, stub_client: httpx.AsyncClient
) -> None:
    assert BlueskyAdapter(settings, stub_client).is_configured()
    assert MastodonAdapter(settings, stub_client).is_configured()
    assert TelegramAdapter(settings, stub_client).is_configured()
    assert DevToAdapter(settings, stub_client).is_configured()
    assert GitHubGistAdapter(settings, stub_client).is_configured()
    assert LinkedInAdapter(settings, stub_client).is_configured()
    assert XAdapter(settings, stub_client).is_configured()
    assert RedditAdapter(settings, stub_client).is_configured()
    assert HashnodeAdapter(settings, stub_client).is_configured()
