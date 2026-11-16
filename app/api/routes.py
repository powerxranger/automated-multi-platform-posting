"""HTTP layer: the thin, typed surface described in the brief."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Header, Request, status

from app.config import Settings
from app.logging import request_id_ctx
from app.schemas import (
    ErrorResponse,
    HealthResponse,
    PlatformInfo,
    PlatformsResponse,
    PostingRequest,
    PostingResponse,
    ValidationIssue,
    ValidationRequest,
    ValidationResponse,
)
from app.services.posting_service import PostingService
from app.services.url_validator import ValidationProblem, parse_message

router = APIRouter()


def _service(request: Request) -> PostingService:
    return cast(PostingService, request.app.state.posting_service)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


@router.post(
    "/posting",
    response_model=PostingResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish one message to every enabled platform",
    description=(
        "Validates the message (max 200 characters, exactly one public CTA link), "
        "then publishes it to every configured platform **concurrently**.\n\n"
        "A failure on one platform is isolated: the others still publish and the "
        "response contains one result row per attempted platform.\n\n"
        "Send an `Idempotency-Key` header to make repeated calls return the "
        "original response instead of posting twice."
    ),
    responses={
        422: {"model": ErrorResponse, "description": "Invalid message or URL."},
        503: {"model": ErrorResponse, "description": "No platform is configured."},
    },
)
async def create_posting(
    request: Request,
    payload: PostingRequest,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Optional key that de-duplicates retries for 10 minutes.",
            max_length=128,
        ),
    ] = None,
) -> PostingResponse:
    service = _service(request)
    message = payload.to_parsed()
    response = await service.publish(message, idempotency_key=idempotency_key)
    response.request_id = request_id_ctx.get()
    return response


@router.get(
    "/platforms",
    response_model=PlatformsResponse,
    summary="Readiness report for every integration",
    description=(
        "Useful before demoing: shows which platforms have credentials present, "
        "which are enabled by `ENABLED_PLATFORMS`, and what is missing."
    ),
)
async def list_platforms(request: Request) -> PlatformsResponse:
    settings = _settings(request)
    service = _service(request)
    enabled_ids = settings.enabled_platform_ids

    items: list[PlatformInfo] = []
    for adapter in service.adapters:
        configured = adapter.is_configured()
        enabled = enabled_ids is None or adapter.platform_id in enabled_ids
        items.append(
            PlatformInfo(
                platform=adapter.platform_name,
                platform_id=adapter.platform_id,
                configured=configured,
                enabled=enabled,
                supports_public_check=adapter.supports_public_check,
                required_settings=(
                    adapter.missing_settings()
                    if not configured
                    else list(adapter.required_settings)
                ),
            )
        )
    return PlatformsResponse(
        total=len(items),
        configured=sum(1 for item in items if item.configured),
        platforms=items,
    )


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(request: Request) -> HealthResponse:
    from datetime import UTC, datetime

    settings = _settings(request)
    service = _service(request)
    configured = sum(1 for adapter in service.adapters if adapter.is_configured())
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
        platforms_configured=configured,
        time_utc=datetime.now(UTC).isoformat(timespec="seconds"),
    )


@router.post(
    "/validate",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Dry-run the validation rules",
    description=(
        "Runs exactly the same validation as `POST /posting` without publishing "
        "anything. Always returns 200; inspect `valid` and `errors`."
    ),
)
async def validate(request: Request, payload: ValidationRequest) -> ValidationResponse:
    max_length = _settings(request).max_message_length
    try:
        parsed = parse_message(payload.message, max_length=max_length)
    except ValidationProblem as exc:
        return ValidationResponse(
            valid=False,
            normalized_message=None,
            errors=[ValidationIssue(field="message", code=exc.code, detail=exc.message)],
        )
    return ValidationResponse(
        valid=True,
        normalized_message=parsed.text,
        cta_url=parsed.url,
        derived_title=parsed.title,
    )


__all__ = ["router"]
