"""Orchestration behaviour: concurrency, isolation, retries, idempotency."""

from __future__ import annotations

import time

import httpx
import pytest

from app.config import Settings
from app.errors import ApiError, ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome
from app.services.posting_service import PostingService
from tests.conftest import StubAdapter, make_client


def build_service(settings: Settings, adapters: list[PlatformAdapter]) -> PostingService:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, text="public page")

    return PostingService(settings, adapters, make_client(handler))


def stub(settings: Settings, platform_id: str, **kwargs: object) -> StubAdapter:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200, text="ok")

    return StubAdapter(
        settings,
        make_client(handler),
        platform_id=platform_id,
        platform_name=platform_id.title(),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_all_platforms_succeed(settings: Settings, message: ParsedMessage) -> None:
    adapters = [stub(settings, "alpha"), stub(settings, "beta")]
    response = await build_service(settings, adapters).publish(message)

    assert response.success is True
    assert [r.platform for r in response.results] == ["Alpha", "Beta"]
    assert response.summary.succeeded == 2
    assert response.summary.failed == 0
    assert all(r.status == "success" for r in response.results)
    assert all(r.posted_url for r in response.results)
    assert all(r.date and r.time for r in response.results)


async def test_one_failure_does_not_stop_the_others(
    settings: Settings, message: ParsedMessage
) -> None:
    adapters = [
        stub(settings, "alpha"),
        stub(
            settings,
            "beta",
            errors=[PlatformError(ErrorCode.AUTH_FAILED, "Authentication failed")],
        ),
        stub(settings, "gamma"),
    ]
    response = await build_service(settings, adapters).publish(message)

    assert response.success is True
    assert response.summary.succeeded == 2
    assert response.summary.failed == 1

    failed = next(r for r in response.results if r.platform == "Beta")
    assert failed.status == "failed"
    assert failed.posted_url is None
    assert failed.public_access is False
    assert failed.date is None and failed.time is None
    assert failed.error == "Authentication failed"


async def test_all_failures_mark_the_request_unsuccessful(
    settings: Settings, message: ParsedMessage
) -> None:
    adapters = [
        stub(
            settings,
            "alpha",
            errors=[
                PlatformError(ErrorCode.NETWORK, "boom"),
                PlatformError(ErrorCode.NETWORK, "boom"),
            ],
        ),
        stub(
            settings,
            "beta",
            errors=[
                PlatformError(ErrorCode.NETWORK, "boom"),
                PlatformError(ErrorCode.NETWORK, "boom"),
            ],
        ),
    ]
    response = await build_service(settings, adapters).publish(message)
    assert response.success is False
    assert response.summary.failed == 2


async def test_unconfigured_platforms_are_reported_not_attempted(
    settings: Settings, message: ParsedMessage
) -> None:
    adapters = [stub(settings, "alpha"), stub(settings, "beta", configured=False)]
    response = await build_service(settings, adapters).publish(message)

    assert len(response.results) == 1
    assert response.summary.platforms_unavailable[0].platform_id == "beta"
    assert "missing credentials" in response.summary.platforms_unavailable[0].reason


async def test_enabled_platforms_filter(settings: Settings, message: ParsedMessage) -> None:
    filtered = settings.model_copy(update={"enabled_platforms": "alpha"})
    adapters = [stub(filtered, "alpha"), stub(filtered, "beta")]
    response = await build_service(filtered, adapters).publish(message)

    assert [r.platform for r in response.results] == ["Alpha"]
    assert response.summary.platforms_unavailable[0].reason.startswith("disabled")


async def test_no_platform_configured_returns_503(
    settings: Settings, message: ParsedMessage
) -> None:
    service = build_service(settings, [])
    with pytest.raises(ApiError) as caught:
        await service.publish(message)
    assert caught.value.status_code == 503
    assert caught.value.code == "NO_PLATFORMS_CONFIGURED"


async def test_retryable_error_is_retried_then_succeeds(
    settings: Settings, message: ParsedMessage
) -> None:
    adapter = stub(
        settings,
        "alpha",
        errors=[PlatformError(ErrorCode.NETWORK, "temporary")],
    )
    response = await build_service(settings, [adapter]).publish(message)

    assert response.results[0].status == "success"
    assert response.results[0].meta is not None
    assert response.results[0].meta.attempts == 2
    assert adapter.calls == 2


async def test_auth_error_is_not_retried(settings: Settings, message: ParsedMessage) -> None:
    adapter = stub(
        settings,
        "alpha",
        errors=[PlatformError(ErrorCode.AUTH_FAILED, "bad token")],
    )
    response = await build_service(settings, [adapter]).publish(message)

    assert response.results[0].status == "failed"
    assert adapter.calls == 1


async def test_timeout_is_isolated(settings: Settings, message: ParsedMessage) -> None:
    slow = settings.model_copy(update={"request_timeout_seconds": 0.05, "max_retries": 0})
    adapters = [
        stub(slow, "alpha", delay=0.3),
        stub(slow, "beta"),
    ]
    response = await build_service(slow, adapters).publish(message)

    slow_result = next(r for r in response.results if r.platform == "Alpha")
    fast_result = next(r for r in response.results if r.platform == "Beta")
    assert slow_result.status == "failed"
    assert "did not respond within" in (slow_result.error or "")
    assert fast_result.status == "success"


async def test_platforms_are_called_concurrently(
    settings: Settings, message: ParsedMessage
) -> None:
    adapters = [stub(settings, f"p{i}", delay=0.1) for i in range(3)]
    started = time.perf_counter()
    await build_service(settings, adapters).publish(message)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25, f"expected parallel execution, took {elapsed:.2f}s"


async def test_idempotency_key_replays_the_cached_response(
    settings: Settings, message: ParsedMessage
) -> None:
    adapter = stub(settings, "alpha")
    service = build_service(settings, [adapter])

    first = await service.publish(message, idempotency_key="abc")
    second = await service.publish(message, idempotency_key="abc")

    assert first.replayed is False
    assert second.replayed is True
    assert adapter.calls == 1
    assert second.results[0].posted_url == first.results[0].posted_url


async def test_public_access_is_verified_when_enabled(
    settings: Settings, message: ParsedMessage
) -> None:
    checked = settings.model_copy(update={"public_check_enabled": True})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                text="<html>public post</html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(201, json={"ok": True})

    service = PostingService(checked, [stub(checked, "alpha")], make_client(handler))
    response = await service.publish(message)

    result = response.results[0]
    assert result.public_access is True
    assert result.meta is not None and result.meta.public_access_verified is True


async def test_public_access_is_unverified_for_login_wall_platforms(
    settings: Settings, message: ParsedMessage
) -> None:
    checked = settings.model_copy(update={"public_check_enabled": True})
    adapter = stub(checked, "alpha", supports_public_check=False)
    response = await build_service(checked, [adapter]).publish(message)

    assert response.results[0].public_access is True
    assert response.results[0].meta is not None
    assert response.results[0].meta.public_access_verified is False


async def test_unexpected_exception_is_contained(
    settings: Settings, message: ParsedMessage
) -> None:
    adapter = stub(settings, "alpha", errors=[RuntimeError("kaboom")])
    adapter2 = stub(settings, "beta")
    response = await build_service(settings, [adapter, adapter2]).publish(message)

    assert response.results[0].status == "failed"
    assert "Unexpected error" in (response.results[0].error or "")
    assert response.results[1].status == "success"


async def test_result_carries_exactly_the_required_fields(
    settings: Settings, message: ParsedMessage
) -> None:
    response = await build_service(settings, [stub(settings, "alpha")]).publish(message)
    payload = response.results[0].model_dump()
    required = {"platform", "status", "posted_url", "public_access", "date", "time", "error"}
    assert required.issubset(payload.keys())


async def test_posted_url_comes_from_the_adapter(
    settings: Settings, message: ParsedMessage
) -> None:
    adapter = stub(settings, "alpha")
    adapter._outcome = PublishOutcome(  # noqa: SLF001 - test double
        posted_url="https://alpha.test/post/42", post_id="42", http_status=200
    )
    response = await build_service(settings, [adapter]).publish(message)
    assert response.results[0].posted_url == "https://alpha.test/post/42"
