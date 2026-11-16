"""Contract every platform integration implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

import httpx

from app.config import Settings
from app.errors import ErrorCode, PlatformError, error_from_response
from app.logging import redact
from app.services.url_validator import ParsedMessage

__all__ = ["ParsedMessage", "PlatformAdapter", "PublishOutcome"]


class PublishOutcome:
    """What a successful publish returns: a real, clickable URL and an id."""

    __slots__ = ("posted_url", "post_id", "http_status")

    def __init__(
        self,
        posted_url: str,
        post_id: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.posted_url = posted_url
        self.post_id = post_id
        self.http_status = http_status

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"PublishOutcome(posted_url={self.posted_url!r}, post_id={self.post_id!r})"


class PlatformAdapter(ABC):
    """One third-party platform.

    Subclasses only know how to talk to their own API. Retries, timeouts,
    concurrency and result shaping are handled by the posting service.
    """

    platform_id: ClassVar[str]
    platform_name: ClassVar[str]
    #: Environment variables this adapter needs in order to be usable.
    required_settings: ClassVar[tuple[str, ...]] = ()
    #: False when the platform cannot be checked anonymously (login walls).
    supports_public_check: ClassVar[bool] = True

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    # ------------------------------------------------------------- contract --
    @abstractmethod
    def is_configured(self) -> bool:
        """True when every required credential is present."""

    @abstractmethod
    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        """Publish exactly once. Raises `PlatformError` on failure."""

    # -------------------------------------------------------------- helpers --
    def missing_settings(self) -> list[str]:
        return [
            name
            for name in self.required_settings
            if not str(getattr(self.settings, name.lower(), "") or "").strip()
        ]

    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: Any | None = None,
        data: Mapping[str, Any] | None = None,
        auth: Any | None = None,
    ) -> httpx.Response:
        """HTTP call with uniform error translation."""
        try:
            response = await self.client.request(
                method,
                url,
                headers=dict(headers or {}),
                json=json,
                data=data,
                auth=auth,
            )
        except httpx.TimeoutException as exc:
            raise PlatformError(
                ErrorCode.TIMEOUT,
                f"{self.platform_name} did not respond in time.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise PlatformError(
                ErrorCode.NETWORK,
                f"Network error while contacting {self.platform_name}: {redact(repr(exc))}",
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            raise error_from_response(self.platform_name, response)
        return response

    def json_body(self, response: httpx.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise PlatformError(
                ErrorCode.UNEXPECTED,
                f"{self.platform_name} returned a non-JSON response "
                f"(HTTP {response.status_code}): {redact(response.text[:200])}",
            ) from exc
        if not isinstance(payload, Mapping):
            raise PlatformError(
                ErrorCode.UNEXPECTED,
                f"{self.platform_name} returned an unexpected payload type.",
            )
        return payload

    def _require(self, *names: str) -> list[str]:
        missing: list[str] = []
        for name in names:
            value = getattr(self.settings, name, None)
            if not str(value or "").strip():
                missing.append(name.upper())
        return missing

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} id={self.platform_id}>"
