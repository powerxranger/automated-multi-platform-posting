"""OAuth 1.0a signing (used by the X adapter)."""

from __future__ import annotations

from app.platforms.oauth1 import oauth1_header

BASE = {
    "consumer_key": "consumer-key",
    "consumer_secret": "consumer-secret",
    "token": "access-token",
    "token_secret": "access-secret",
    "timestamp": 1700000000,
    "nonce": "fixed-nonce",
}


def test_header_contains_all_required_parameters() -> None:
    header = oauth1_header("POST", "https://api.x.com/2/tweets", **BASE)
    assert header.startswith("OAuth ")
    for expected in (
        'oauth_consumer_key="consumer-key"',
        'oauth_nonce="fixed-nonce"',
        'oauth_timestamp="1700000000"',
        'oauth_signature_method="HMAC-SHA1"',
        'oauth_version="1.0"',
        'oauth_token="access-token"',
    ):
        assert expected in header
    assert "oauth_signature=" in header


def test_signature_is_deterministic_for_fixed_inputs() -> None:
    first = oauth1_header("POST", "https://api.x.com/2/tweets", **BASE)
    second = oauth1_header("POST", "https://api.x.com/2/tweets", **BASE)
    assert first == second


def test_different_nonce_produces_a_different_signature() -> None:
    first = oauth1_header("POST", "https://api.x.com/2/tweets", **BASE)
    second = oauth1_header("POST", "https://api.x.com/2/tweets", **{**BASE, "nonce": "other-nonce"})
    assert first != second


def test_query_parameters_are_included_in_the_signature() -> None:
    plain = oauth1_header("GET", "https://api.x.com/2/tweets", **BASE)
    with_query = oauth1_header("GET", "https://api.x.com/2/tweets?ids=1", **BASE)
    assert plain != with_query
