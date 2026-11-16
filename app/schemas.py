"""Request / response models.

The request model performs the full validation chain so that invalid input is
rejected by FastAPI before any network call happens. Semantic rules live in
`app.services.url_validator`; this module only adapts them to Pydantic errors.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.services.url_validator import (
    ParsedMessage,
    ValidationProblem,
    extract_urls,
    parse_message,
)

EXAMPLE_MESSAGE = (
    "Check out our latest business platform and grow your online visibility. https://example.com"
)


class PostingRequest(BaseModel):
    """Body of `POST /posting`."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"message": EXAMPLE_MESSAGE}},
    )

    message: str = Field(
        ...,
        description=(
            "The message to publish. Maximum 200 characters after whitespace "
            "normalisation and it must contain exactly one public http(s) link."
        ),
        examples=[EXAMPLE_MESSAGE],
    )

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        try:
            return parse_message(value).text
        except ValidationProblem as exc:
            raise PydanticCustomError(exc.code, exc.message) from None

    @property
    def cta_url(self) -> str:
        return extract_urls(self.message)[0]

    def to_parsed(self) -> ParsedMessage:
        return parse_message(self.message)


class ValidationIssue(BaseModel):
    field: str = Field(description="Offending request field.")
    code: str = Field(description="Stable machine-readable reason.")
    detail: str = Field(description="Human readable explanation.")


class ErrorDetail(BaseModel):
    code: str = Field(examples=["VALIDATION_ERROR"])
    message: str
    fields: list[ValidationIssue] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    request_id: str
    error: ErrorDetail


class ResultMeta(BaseModel):
    """Diagnostics that deliberately stay out of the spec's flat fields."""

    http_status: int | None = None
    latency_ms: int = 0
    attempts: int = 1
    public_access_verified: bool = False
    timezone: str = "UTC"
    post_id: str | None = None
    checked_at_utc: str | None = None


class PlatformResult(BaseModel):
    """One row per attempted platform - exactly the fields from the brief."""

    platform: str = Field(examples=["Bluesky"])
    status: Literal["success", "failed"] = Field(examples=["success"])
    posted_url: str | None = Field(default=None, examples=["https://bsky.app/..."])
    public_access: bool | None = Field(
        default=None,
        description="True when the post is reachable without authentication.",
    )
    date: str | None = Field(default=None, examples=["2026-11-16"])
    time: str | None = Field(default=None, examples=["14:32:05"])
    error: str | None = Field(default=None, examples=["Authentication failed"])
    meta: ResultMeta | None = None


class UnavailablePlatform(BaseModel):
    platform: str
    platform_id: str
    reason: str


class Summary(BaseModel):
    total: int = Field(description="Platforms attempted.")
    succeeded: int
    failed: int
    duration_ms: int
    platforms_unavailable: list[UnavailablePlatform] = Field(default_factory=list)


class PostingResponse(BaseModel):
    success: bool = Field(description="True when at least one platform published the message.")
    request_id: str
    message: str
    summary: Summary
    results: list[PlatformResult]
    replayed: bool = Field(
        default=False,
        description="True when the response was served from the idempotency cache.",
    )


class PlatformInfo(BaseModel):
    platform: str
    platform_id: str
    configured: bool
    enabled: bool
    supports_public_check: bool
    required_settings: list[str]


class PlatformsResponse(BaseModel):
    total: int
    configured: int
    platforms: list[PlatformInfo]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    environment: str
    platforms_configured: int
    time_utc: str


class ValidationResponse(BaseModel):
    valid: bool
    normalized_message: str | None = None
    cta_url: str | None = None
    derived_title: str | None = None
    errors: list[ValidationIssue] = Field(default_factory=list)


class ValidationRequest(BaseModel):
    """Unvalidated body for `POST /validate` (the rules run in the handler)."""

    message: str = Field(default="", description="Candidate message to check.")

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"message": EXAMPLE_MESSAGE}},
    )


JsonDict = dict[str, Any]
