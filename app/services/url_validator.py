"""Pure, dependency-free message validation.

Kept separate from the Pydantic schema so the rules can be unit tested directly
and reused by the optional `/validate` endpoint.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.config import get_settings

#: Matches http(s) URLs; trailing punctuation is stripped afterwards.
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}'\">"
_TLD_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_MAX_URL_LENGTH = 2048


class ValidationProblem(Exception):
    """A user-facing validation failure with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """A validated message plus the derived fields platforms need."""

    text: str
    url: str
    title: str


def normalize_message(raw: str) -> str:
    """Collapse whitespace and trim, so length checks are meaningful."""
    return re.sub(r"\s+", " ", raw.replace("\u200b", "")).strip()


def extract_urls(text: str) -> list[str]:
    """Return every http(s) URL in `text`, without trailing punctuation."""
    found: list[str] = []
    for match in URL_PATTERN.finditer(text):
        candidate = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        if candidate:
            found.append(candidate)
    return found


def _hostname_problem(hostname: str) -> str | None:
    lowered = hostname.lower().rstrip(".")
    if lowered in _LOCAL_HOSTNAMES or lowered.endswith(".localhost"):
        return "localhost addresses are not publicly reachable"
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        pass
    else:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return "private or reserved IP addresses are not publicly reachable"
        return None

    if "." not in lowered:
        return "the hostname needs a top-level domain (for example example.com)"
    tld = lowered.rsplit(".", 1)[-1]
    if len(tld) < 2 or not _TLD_PATTERN.match(tld):
        return f"'{tld}' is not a valid top-level domain"
    return None


def url_problem(url: str) -> str | None:
    """Return a human readable reason why `url` is unusable, or `None`."""
    if len(url) > _MAX_URL_LENGTH:
        return f"the URL is longer than {_MAX_URL_LENGTH} characters"
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        return f"the URL cannot be parsed ({exc})"

    if parsed.scheme.lower() not in {"http", "https"}:
        return "only http and https URLs are supported"
    if not parsed.netloc:
        return "the URL is missing a hostname"
    if parsed.username or parsed.password:
        return "credentials embedded in the URL are not allowed"
    if parsed.hostname is None:
        return "the URL is missing a hostname"
    try:
        _ = parsed.port  # raises ValueError for malformed ports
    except ValueError:
        return "the URL contains an invalid port"
    hostname_problem = _hostname_problem(parsed.hostname)
    if hostname_problem:
        return hostname_problem
    return None


def derive_title(text: str, url: str, limit: int = 80) -> str:
    """Build a short title for platforms that require one (Dev.to, Reddit...)."""
    without_url = text.replace(url, " ").strip(" -:|,.;")
    without_url = re.sub(r"\s+", " ", without_url).strip()
    if not without_url:
        return "New update"
    if len(without_url) <= limit:
        return without_url
    return without_url[: limit - 1].rstrip() + "…"


def parse_message(raw: str, max_length: int | None = None) -> ParsedMessage:
    """Validate and normalise a raw message. Raises `ValidationProblem`."""
    if max_length is None:
        max_length = get_settings().max_message_length

    if not isinstance(raw, str):  # pragma: no cover - Pydantic guards this
        raise ValidationProblem("invalid_type", "Message must be a string.")

    text = normalize_message(raw)
    if not text:
        raise ValidationProblem("message_empty", "Message must not be empty.")
    if len(text) > max_length:
        raise ValidationProblem(
            "message_too_long",
            f"Message is {len(text)} characters; the maximum is {max_length}.",
        )

    urls = extract_urls(text)
    if not urls:
        raise ValidationProblem(
            "link_count",
            "Exactly one CTA link is required; none was found.",
        )
    if len(urls) > 1:
        listed = ", ".join(urls[:3])
        raise ValidationProblem(
            "link_count",
            f"Exactly one CTA link is required; {len(urls)} were found ({listed}).",
        )

    url = urls[0]
    problem = url_problem(url)
    if problem:
        raise ValidationProblem("invalid_url", f"The CTA link is invalid: {problem}.")

    return ParsedMessage(text=text, url=url, title=derive_title(text, url))
