"""Minimal RFC 5849 (OAuth 1.0a) HMAC-SHA1 header signer.

X/Twitter still requires OAuth 1.0a user context for `POST /2/tweets`. The
implementation is intentionally tiny and dependency free so it can be unit
tested without network access.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping
from urllib.parse import parse_qsl, quote, urlsplit

_UNRESERVED = "-._~"


def _pct(value: str) -> str:
    return quote(str(value), safe=_UNRESERVED)


def oauth1_header(
    method: str,
    url: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    token: str,
    token_secret: str,
    timestamp: int | None = None,
    nonce: str | None = None,
    extra: Mapping[str, str] | None = None,
) -> str:
    """Build the `Authorization: OAuth ...` header value for a JSON request."""
    oauth_params: dict[str, str] = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp if timestamp is not None else int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    if extra:
        oauth_params.update(extra)

    parsed = urlsplit(url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    all_pairs = sorted([*query_pairs, *oauth_params.items()])

    encoded_pairs = "&".join(f"{_pct(key)}={_pct(value)}" for key, value in all_pairs)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    base_string = "&".join([method.upper(), _pct(base_url), _pct(encoded_pairs)])
    signing_key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    digest = hmac.new(
        signing_key.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1
    ).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode("ascii")

    header_pairs = ", ".join(
        f'{_pct(key)}="{_pct(value)}"' for key, value in sorted(oauth_params.items())
    )
    return f"OAuth {header_pairs}"
