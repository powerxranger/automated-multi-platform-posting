"""Error taxonomy shared by every platform adapter and the HTTP layer."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

import httpx

from app.logging import redact


class ErrorCode(StrEnum):
    """Stable machine-readable error codes returned to API clients."""

    CONFIG_MISSING = "config_missing"
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PLATFORM_REJECTED = "platform_rejected"
    UNEXPECTED = "unexpected"


#: Codes that are worth retrying. Anything else (bad token, rejected payload)
#: would fail identically on a second attempt.
RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(
    {ErrorCode.RATE_LIMITED, ErrorCode.TIMEOUT, ErrorCode.NETWORK}
)


class PlatformError(Exception):
    """A single platform failed. Never aborts the whole request."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        http_status: int | None = None,
        retryable: bool | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after
        self._retryable = retryable

    @property
    def retryable(self) -> bool:
        if self._retryable is not None:
            return self._retryable
        return self.code in RETRYABLE_CODES

    def as_text(self) -> str:
        """Human readable, secret-free description for the API response."""
        return redact(self.message)


class ApiError(Exception):
    """An error that maps directly onto the HTTP error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        fields: list[Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = list(fields or [])


def _body_snippet(response: httpx.Response, limit: int = 300) -> str:
    try:
        text = response.text
    except Exception:  # pragma: no cover - defensive
        return ""
    text = " ".join(text.split())
    return text[:limit]


def error_from_response(platform: str, response: httpx.Response) -> PlatformError:
    """Translate a non-2xx HTTP response into our error taxonomy."""
    status = response.status_code
    snippet = _body_snippet(response)
    retry_after_header = response.headers.get("retry-after")
    retry_after: float | None = None
    if retry_after_header:
        try:
            retry_after = float(retry_after_header)
        except ValueError:
            retry_after = None

    if status in (401, 403):
        return PlatformError(
            ErrorCode.AUTH_FAILED,
            f"{platform} rejected the credentials (HTTP {status}). {snippet}".strip(),
            http_status=status,
        )
    if status == 429:
        return PlatformError(
            ErrorCode.RATE_LIMITED,
            f"{platform} rate limit hit (HTTP 429). {snippet}".strip(),
            http_status=status,
            retry_after=retry_after,
        )
    if status >= 500:
        return PlatformError(
            ErrorCode.NETWORK,
            f"{platform} server error (HTTP {status}). {snippet}".strip(),
            http_status=status,
        )
    return PlatformError(
        ErrorCode.PLATFORM_REJECTED,
        f"{platform} rejected the request (HTTP {status}). {snippet}".strip(),
        http_status=status,
    )
