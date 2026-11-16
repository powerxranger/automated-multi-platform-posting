"""Anonymous public-access verification."""

from __future__ import annotations

import httpx

from app.services.public_access import check_public_access
from tests.conftest import make_client

URL = "https://social.test/@tester/123"


async def test_public_html_page() -> None:
    client = make_client(
        lambda request: httpx.Response(
            200,
            text="<html><body>Hello world</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    result = await check_public_access(client, URL)
    assert result.public is True
    assert result.verified is True


async def test_login_wall_page_is_not_public() -> None:
    client = make_client(
        lambda request: httpx.Response(
            200,
            text="<html><body>Sign in to continue</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    result = await check_public_access(client, URL)
    assert result.public is False
    assert result.verified is True


async def test_redirect_to_login_is_not_public() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            return httpx.Response(
                200,
                text="<html>Log in to continue</html>",
                headers={"content-type": "text/html"},
            )
        return httpx.Response(302, headers={"location": "https://social.test/login"})

    result = await check_public_access(make_client(handler), URL)
    assert result.public is False
    assert result.verified is True


async def test_forbidden_is_not_public() -> None:
    client = make_client(lambda request: httpx.Response(403, text="no"))
    result = await check_public_access(client, URL)
    assert result.public is False
    assert result.verified is True


async def test_deleted_post_is_not_public() -> None:
    client = make_client(lambda request: httpx.Response(404, text="gone"))
    result = await check_public_access(client, URL)
    assert result.public is False


async def test_network_error_is_inconclusive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("dns failure", request=request)

    result = await check_public_access(make_client(handler), URL)
    assert result.public is None
    assert result.verified is False
