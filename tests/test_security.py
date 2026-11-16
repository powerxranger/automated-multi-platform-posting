"""Credentials must never reach logs or API responses."""

from __future__ import annotations

import logging

import pytest

from app.errors import ErrorCode, PlatformError
from app.logging import (
    JsonFormatter,
    redact,
    register_secret,
    request_id_ctx,
    reset_secrets,
)

TOKEN = "super-secret-token-value-123456"


@pytest.fixture(autouse=True)
def _clean_secrets() -> None:
    reset_secrets()
    yield
    reset_secrets()


def test_registered_secret_is_redacted() -> None:
    register_secret(TOKEN)
    assert redact(f"Authorization: Bearer {TOKEN}") == "Authorization: Bearer ***"


def test_short_values_are_not_registered() -> None:
    register_secret("abc")
    assert redact("abc") == "abc"


def test_platform_error_text_is_redacted() -> None:
    register_secret(TOKEN)
    error = PlatformError(ErrorCode.AUTH_FAILED, f"token {TOKEN} was rejected")
    assert TOKEN not in error.as_text()
    assert "***" in error.as_text()


def test_log_lines_are_redacted() -> None:
    register_secret(TOKEN)
    token = request_id_ctx.set("req-1")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=f"calling api with {TOKEN}",
            args=(),
            exc_info=None,
        )
        record.data = {"header": f"Bearer {TOKEN}"}  # type: ignore[attr-defined]
        payload = JsonFormatter().format(record)
    finally:
        request_id_ctx.reset(token)

    assert TOKEN not in payload
    assert "req-1" in payload
    assert "***" in payload


def test_all_configured_secrets_are_registered(settings: object) -> None:
    from tests.conftest import build_settings

    configured = build_settings()
    for secret in configured.all_secrets:
        register_secret(secret)
    assert redact(configured.bluesky_app_password or "") == "***"
    assert redact(configured.github_token or "") == "***"
