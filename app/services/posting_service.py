"""Orchestration: publish to every enabled platform concurrently, isolate
failures, retry only what is worth retrying, and shape the response.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app.config import Settings
from app.errors import ApiError, ErrorCode, PlatformError
from app.logging import get_logger, redact
from app.platforms.base import PlatformAdapter, PublishOutcome
from app.schemas import (
    PlatformResult,
    PostingResponse,
    ResultMeta,
    Summary,
    UnavailablePlatform,
)
from app.services.public_access import PublicCheckResult, check_public_access
from app.services.url_validator import ParsedMessage

logger = get_logger(__name__)


class PostingService:
    def __init__(
        self,
        settings: Settings,
        adapters: list[PlatformAdapter],
        client: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self.adapters = adapters
        self.client = client
        self._cache: dict[str, tuple[float, PostingResponse]] = {}
        self._cache_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_platforms)
        try:
            self._tz: tzinfo = ZoneInfo(settings.app_timezone)
        except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover - bad config
            logger.warning(
                "unknown_timezone_falling_back_to_utc",
                extra={"data": {"timezone": settings.app_timezone}},
            )
            self._tz = UTC

    # ------------------------------------------------------------- snapshot --
    def platform_snapshot(self) -> tuple[list[PlatformAdapter], list[UnavailablePlatform]]:
        """Split adapters into "will be attempted" and "cannot be attempted"."""
        enabled_ids = self.settings.enabled_platform_ids
        available: list[PlatformAdapter] = []
        unavailable: list[UnavailablePlatform] = []

        for adapter in self.adapters:
            if enabled_ids is not None and adapter.platform_id not in enabled_ids:
                unavailable.append(
                    UnavailablePlatform(
                        platform=adapter.platform_name,
                        platform_id=adapter.platform_id,
                        reason="disabled via ENABLED_PLATFORMS",
                    )
                )
                continue
            if not adapter.is_configured():
                missing = ", ".join(adapter.missing_settings())
                unavailable.append(
                    UnavailablePlatform(
                        platform=adapter.platform_name,
                        platform_id=adapter.platform_id,
                        reason=f"missing credentials: {missing}",
                    )
                )
                continue
            available.append(adapter)
        return available, unavailable

    # -------------------------------------------------------------- publish --
    async def publish(
        self,
        message: ParsedMessage,
        idempotency_key: str | None = None,
    ) -> PostingResponse:
        started = time.perf_counter()

        if idempotency_key:
            cached = await self._cache_get(idempotency_key)
            if cached is not None:
                logger.info(
                    "idempotent_replay",
                    extra={"data": {"idempotency_key": idempotency_key}},
                )
                return cached.model_copy(update={"replayed": True})

        available, unavailable = self.platform_snapshot()
        if not available:
            raise ApiError(
                status_code=503,
                code="NO_PLATFORMS_CONFIGURED",
                message=(
                    "No platform is configured. Fill in at least one set of "
                    "credentials in .env (see .env.example) and restart the server."
                ),
                fields=[
                    {
                        "field": item.platform,
                        "code": item.platform_id,
                        "detail": item.reason,
                    }
                    for item in unavailable
                ],
            )

        tasks = [asyncio.create_task(self._publish_one(adapter, message)) for adapter in available]
        results = await asyncio.gather(*tasks)

        succeeded = sum(1 for result in results if result.status == "success")
        duration_ms = int((time.perf_counter() - started) * 1000)
        response = PostingResponse(
            success=succeeded > 0,
            request_id="",  # filled by the HTTP layer
            message=message.text,
            summary=Summary(
                total=len(results),
                succeeded=succeeded,
                failed=len(results) - succeeded,
                duration_ms=duration_ms,
                platforms_unavailable=unavailable,
            ),
            results=results,
        )

        if idempotency_key:
            await self._cache_put(idempotency_key, response)

        logger.info(
            "posting_completed",
            extra={
                "data": {
                    "total": len(results),
                    "succeeded": succeeded,
                    "failed": len(results) - succeeded,
                    "duration_ms": duration_ms,
                }
            },
        )
        return response

    # ---------------------------------------------------------- one platform --
    async def _publish_one(
        self, adapter: PlatformAdapter, message: ParsedMessage
    ) -> PlatformResult:
        started = time.perf_counter()
        attempts = 0
        outcome: PublishOutcome | None = None
        error_text: str | None = None
        http_status: int | None = None

        while True:
            attempts += 1
            try:
                async with self._semaphore:
                    outcome = await asyncio.wait_for(
                        adapter.publish_once(message),
                        timeout=self.settings.request_timeout_seconds,
                    )
            except PlatformError as exc:
                http_status = exc.http_status
                if exc.retryable and attempts <= self.settings.max_retries:
                    await self._sleep_before_retry(attempts, exc.retry_after)
                    continue
                error_text = exc.as_text()
                break
            except TimeoutError:
                http_status = None
                if attempts <= self.settings.max_retries:
                    await self._sleep_before_retry(attempts, None)
                    continue
                error_text = (
                    f"{adapter.platform_name} did not respond within "
                    f"{self.settings.request_timeout_seconds:g}s."
                )
                break
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                logger.exception(
                    "adapter_crashed",
                    extra={"data": {"platform": adapter.platform_name}},
                )
                error_text = redact(
                    f"Unexpected error in the {adapter.platform_name} integration: "
                    f"{type(exc).__name__}: {exc}"
                )
                break
            else:
                break

        now = datetime.now(self._tz)
        if outcome is None:
            result = PlatformResult(
                platform=adapter.platform_name,
                status="failed",
                posted_url=None,
                public_access=False,
                date=None,
                time=None,
                error=error_text or "Unknown failure.",
                meta=ResultMeta(
                    http_status=http_status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    attempts=attempts,
                    public_access_verified=False,
                    timezone=str(self._tz),
                ),
            )
            logger.warning(
                "platform_failed",
                extra={
                    "data": {
                        "platform": adapter.platform_name,
                        "error": result.error,
                        "attempts": attempts,
                    }
                },
            )
            return result

        public, verified = await self._public_access(adapter, outcome.posted_url)
        result = PlatformResult(
            platform=adapter.platform_name,
            status="success",
            posted_url=outcome.posted_url,
            public_access=public,
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M:%S"),
            error=None,
            meta=ResultMeta(
                http_status=outcome.http_status,
                latency_ms=int((time.perf_counter() - started) * 1000),
                attempts=attempts,
                public_access_verified=verified,
                timezone=str(self._tz),
                post_id=outcome.post_id,
                checked_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        logger.info(
            "platform_published",
            extra={
                "data": {
                    "platform": adapter.platform_name,
                    "posted_url": outcome.posted_url,
                    "public_access": public,
                    "public_access_verified": verified,
                    "attempts": attempts,
                    "latency_ms": result.meta.latency_ms if result.meta else None,
                }
            },
        )
        return result

    async def _public_access(
        self, adapter: PlatformAdapter, posted_url: str
    ) -> tuple[bool | None, bool]:
        if not adapter.supports_public_check:
            # Public by design, but not anonymously verifiable (login wall).
            return True, False
        if not self.settings.public_check_enabled:
            return None, False
        result: PublicCheckResult = await check_public_access(
            self.client,
            posted_url,
            timeout_seconds=self.settings.public_check_timeout_seconds,
        )
        return result.public, result.verified

    async def _sleep_before_retry(self, attempt: int, retry_after: float | None) -> None:
        base = self.settings.retry_backoff_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0, base / 2) if base else 0.0
        delay = min(retry_after if retry_after is not None else base + jitter, 3.0)
        if delay > 0:
            await asyncio.sleep(delay)

    # ---------------------------------------------------------- idempotency --
    async def _cache_get(self, key: str) -> PostingResponse | None:
        if self.settings.idempotency_ttl_seconds <= 0:
            return None
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires_at, response = entry
            if time.monotonic() > expires_at:
                self._cache.pop(key, None)
                return None
            return response

    async def _cache_put(self, key: str, response: PostingResponse) -> None:
        if self.settings.idempotency_ttl_seconds <= 0:
            return
        async with self._cache_lock:
            now = time.monotonic()
            for stale in [k for k, (exp, _) in self._cache.items() if exp < now]:
                self._cache.pop(stale, None)
            self._cache[key] = (now + self.settings.idempotency_ttl_seconds, response)


__all__ = ["PostingService", "ErrorCode"]
