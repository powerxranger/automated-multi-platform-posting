"""HTTP contract tests: status codes, envelopes, headers, OpenAPI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.errors import ErrorCode, PlatformError
from app.main import create_app
from app.services.posting_service import PostingService
from tests.conftest import StubAdapter

MESSAGE = "Check out our latest business platform. https://example.com"


@asynccontextmanager
async def running(settings: Settings) -> AsyncIterator[tuple[AsyncClient, FastAPI]]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app


def install_adapters(app: FastAPI, settings: Settings, adapters: list[StubAdapter]) -> None:
    app.state.posting_service = PostingService(settings, list(adapters), app.state.http_client)


def stub(app: FastAPI, settings: Settings, name: str, **kwargs: Any) -> StubAdapter:
    return StubAdapter(
        settings,
        app.state.http_client,
        platform_id=name.lower(),
        platform_name=name,
        **kwargs,
    )


async def test_health(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["platforms_configured"] == 5


async def test_root_points_at_docs(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


async def test_platforms_readiness(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.get("/platforms")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["configured"] == 5
    assert {item["platform_id"] for item in body["platforms"]} >= {"bluesky", "telegram"}


async def test_platforms_readiness_without_credentials() -> None:
    empty = Settings(_env_file=None)
    async with running(empty) as (client, _):
        response = await client.get("/platforms")
    body = response.json()
    assert body["configured"] == 0
    assert "BLUESKY_HANDLE" in body["platforms"][0]["required_settings"]


async def test_validate_endpoint_accepts_good_message(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.post("/validate", json={"message": MESSAGE})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["cta_url"] == "https://example.com"
    assert body["derived_title"].startswith("Check out")


async def test_validate_endpoint_reports_problems(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.post("/validate", json={"message": "no link here"})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["errors"][0]["code"] == "link_count"


@pytest.mark.parametrize(
    ("message", "expected_code"),
    [
        ("No link at all", "link_count"),
        ("Two https://a.example.com and https://b.example.com", "link_count"),
        ("x" * 201 + " https://example.com", "message_too_long"),
        ("Local only http://localhost:4000/x", "invalid_url"),
        ("Bad url http://example", "invalid_url"),
        ("", "message_empty"),
    ],
)
async def test_posting_validation_errors(
    settings: Settings, message: str, expected_code: str
) -> None:
    async with running(settings) as (client, _):
        response = await client.post("/posting", json={"message": message})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["fields"][0]["field"] == "message"
    assert body["error"]["fields"][0]["code"] == expected_code


async def test_posting_rejects_unknown_fields(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.post(
            "/posting", json={"message": MESSAGE, "platforms": ["bluesky"]}
        )
    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["code"] == "extra_forbidden"


async def test_posting_rejects_malformed_json(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.post(
            "/posting",
            content="{not json",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_posting_happy_path(settings: Settings) -> None:
    async with running(settings) as (client, app):
        install_adapters(app, settings, [stub(app, settings, "Alpha")])
        response = await client.post("/posting", json={"message": MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["request_id"] == response.headers["x-request-id"]
    assert len(body["results"]) == 1
    result = body["results"]
    result = result[0]
    assert set(result) >= {
        "platform",
        "status",
        "posted_url",
        "public_access",
        "date",
        "time",
        "error",
    }
    assert result["platform"] == "Alpha"
    assert result["status"] == "success"
    assert result["error"] is None
    assert body["summary"]["total"] == 1


async def test_posting_partial_failure_is_still_200(settings: Settings) -> None:
    async with running(settings) as (client, app):
        good = stub(app, settings, "Alpha")
        bad = stub(
            app,
            settings,
            "Beta",
            errors=[PlatformError(ErrorCode.AUTH_FAILED, "Authentication failed")],
        )
        install_adapters(app, settings, [good, bad])
        response = await client.post("/posting", json={"message": MESSAGE})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["summary"] == {
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "duration_ms": body["summary"]["duration_ms"],
        "platforms_unavailable": [],
    }
    failed = body["results"][1]
    assert failed["status"] == "failed"
    assert failed["error"] == "Authentication failed"


async def test_posting_without_configured_platforms_returns_503() -> None:
    empty = Settings(_env_file=None)
    async with running(empty) as (client, _):
        response = await client.post("/posting", json={"message": MESSAGE})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "NO_PLATFORMS_CONFIGURED"
    assert len(body["error"]["fields"]) == 5


async def test_idempotency_header_replays(settings: Settings) -> None:
    async with running(settings) as (client, app):
        adapter = stub(app, settings, "Alpha")
        install_adapters(app, settings, [adapter])
        first = await client.post(
            "/posting", json={"message": MESSAGE}, headers={"Idempotency-Key": "key-1"}
        )
        second = await client.post(
            "/posting", json={"message": MESSAGE}, headers={"Idempotency-Key": "key-1"}
        )

    assert first.status_code == second.status_code == 200
    assert first.json()["replayed"] is False
    assert second.json()["replayed"] is True
    assert adapter.calls == 1
    assert second.json()["results"][0]["posted_url"] == first.json()["results"][0]["posted_url"]


async def test_unknown_route_uses_the_error_envelope(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.get("/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "HTTP_404"


async def test_openapi_document_exposes_the_endpoint(settings: Settings) -> None:
    async with running(settings) as (client, _):
        document = (await client.get("/openapi.json")).json()
    assert "/posting" in document["paths"]
    assert "post" in document["paths"]["/posting"]
    schema = document["paths"]["/posting"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert schema["$ref"].endswith("PostingRequest")


async def test_docs_page_is_served(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


async def test_health_does_not_leak_credentials(settings: Settings) -> None:
    async with running(settings) as (client, _):
        response = await client.get("/health")
    assert "telegram-token" not in response.text
    assert "test-github-token" not in response.text
