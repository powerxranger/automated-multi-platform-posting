"""Application factory and ASGI entry point.

Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 4000
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.config import Settings, get_settings
from app.errors import ApiError
from app.logging import (
    configure_logging,
    get_logger,
    redact,
    register_secrets,
    request_id_ctx,
)
from app.platforms.registry import build_registry
from app.schemas import (
    ErrorDetail,
    ErrorResponse,
    ValidationIssue,
)
from app.services.posting_service import PostingService

logger = get_logger(__name__)

DESCRIPTION = """
Publish **one** short message to **many** platforms through their official APIs.

* Validates the message (≤ 200 characters, exactly one public CTA link).
* Publishes concurrently, with per-platform timeouts, retries and error isolation.
* Returns one result row per platform, including the public URL and whether that
  URL is anonymously reachable.

Credentials live in `.env`; a platform without credentials is reported as
unavailable instead of failing the request. See `GET /platforms`.
"""


def _error_response(
    status_code: int,
    code: str,
    message: str,
    fields: Sequence[Mapping[str, Any]] | None = None,
) -> JSONResponse:
    envelope = ErrorResponse(
        request_id=request_id_ctx.get(),
        error=ErrorDetail(
            code=code,
            message=message,
            fields=[ValidationIssue(**field) for field in (fields or [])],
        ),
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump())


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        register_secrets(settings.all_secrets)

        client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.request_timeout_seconds,
                connect=settings.connect_timeout_seconds,
            ),
            headers={"User-Agent": settings.user_agent},
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            follow_redirects=False,
        )
        adapters = build_registry(settings, client)
        app.state.settings = settings
        app.state.http_client = client
        app.state.posting_service = PostingService(settings, adapters, client)

        configured = [a.platform_name for a in adapters if a.is_configured()]
        logger.info(
            "application_started",
            extra={
                "data": {
                    "version": settings.app_version,
                    "environment": settings.environment,
                    "platforms_configured": configured,
                    "timeout_s": settings.request_timeout_seconds,
                }
            },
        )
        try:
            yield
        finally:
            await client.aclose()
            logger.info("application_stopped")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_tags=[
            {"name": "posting", "description": "Publish and inspect platform readiness."}
        ],
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next: Any) -> Any:
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming.strip()[:64] if incoming and incoming.strip() else uuid4().hex
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields: list[dict[str, Any]] = []
        for error in exc.errors():
            location = [str(part) for part in error.get("loc", ()) if part != "body"]
            fields.append(
                {
                    "field": ".".join(location) or "body",
                    "code": str(error.get("type", "invalid")),
                    "detail": redact(str(error.get("msg", "Invalid value."))),
                }
            )
        return _error_response(
            422,
            "VALIDATION_ERROR",
            "The request body is invalid. See the fields array for details.",
            fields,
        )

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.fields)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            exc.status_code,
            f"HTTP_{exc.status_code}",
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return _error_response(
            500,
            "INTERNAL_ERROR",
            "Unexpected server error. The request id can be used to find the logs.",
        )

    app.include_router(router, tags=["posting"])

    @app.get("/", include_in_schema=False)
    async def index() -> dict[str, Any]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "endpoint": "POST /posting",
            "platforms": "/platforms",
            "health": "/health",
        }

    return app


app = create_app()
