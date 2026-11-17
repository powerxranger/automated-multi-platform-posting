"""Shared test fixtures: no network access is used anywhere in the suite."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome
from app.services.url_validator import parse_message

EXAMPLE_URL = "https://example.com"
EXAMPLE_TEXT = f"Check out our latest business platform. {EXAMPLE_URL}"


def build_settings(**overrides: Any) -> Settings:
    """Credential-complete settings with deterministic, test-friendly knobs."""
    defaults: dict[str, Any] = {
        "app_timezone": "UTC",
        "public_check_enabled": False,
        "retry_backoff_seconds": 0.0,
        "max_retries": 1,
        "request_timeout_seconds": 5.0,
        "idempotency_ttl_seconds": 600,
        "bluesky_handle": "tester.bsky.social",
        "bluesky_app_password": "app-password-0123456789",
        "mastodon_instance_url": "https://mastodon.test",
        "mastodon_access_token": "mastodon-token-0123456789",
        "telegram_bot_token": "123456:telegram-token-0123456789",
        "telegram_channel": "@testchannel",
        "devto_api_key": "devto-key-0123456789",
        "github_token": "test-github-token-value",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest.fixture
def settings() -> Settings:
    return build_settings()


@pytest.fixture
def message() -> ParsedMessage:
    return parse_message(EXAMPLE_TEXT, max_length=200)


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    """An AsyncClient that never touches the network."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class StubAdapter(PlatformAdapter):
    """Configurable adapter used to exercise the orchestration layer."""

    platform_id = "stub"
    platform_name = "Stub"
    supports_public_check = True

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        *,
        platform_id: str = "stub",
        platform_name: str = "Stub",
        configured: bool = True,
        outcome: PublishOutcome | None = None,
        errors: list[Exception] | None = None,
        delay: float = 0.0,
        supports_public_check: bool = True,
    ) -> None:
        super().__init__(settings, client)
        self.platform_id = platform_id  # type: ignore[misc]
        self.platform_name = platform_name  # type: ignore[misc]
        self._configured = configured
        self._outcome = outcome or PublishOutcome(
            posted_url=f"https://stub.test/{platform_id}",
            post_id=f"id-{platform_id}",
            http_status=201,
        )
        self._errors = list(errors or [])
        self._delay = delay
        self.calls = 0
        self.supports_public_check = supports_public_check  # type: ignore[misc]

    def is_configured(self) -> bool:
        return self._configured

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        import asyncio

        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._errors:
            raise self._errors.pop(0)
        return self._outcome


@pytest.fixture
def stub_client() -> httpx.AsyncClient:
    """A MockTransport client, for adapters that never hit the network."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, json={"ok": True})

    return make_client(handler)
