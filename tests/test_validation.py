"""Validation rules: the highest-weight block of the brief."""

from __future__ import annotations

import pytest

from app.services.url_validator import (
    ValidationProblem,
    derive_title,
    extract_urls,
    normalize_message,
    parse_message,
)

URL = "https://example.com"


def problem(text: str) -> ValidationProblem:
    with pytest.raises(ValidationProblem) as caught:
        parse_message(text, max_length=200)
    return caught.value


def test_accepts_brief_example() -> None:
    parsed = parse_message(
        "Check out our latest business platform and grow your online visibility. "
        "https://example.com",
        max_length=200,
    )
    assert parsed.url == "https://example.com"
    assert parsed.text.startswith("Check out")


def test_exactly_200_characters_is_allowed() -> None:
    padding = "a" * (200 - len(URL) - 1)
    text = f"{padding} {URL}"
    assert len(text) == 200
    assert parse_message(text, max_length=200).url == URL


def test_201_characters_is_rejected_with_counts() -> None:
    padding = "a" * (201 - len(URL) - 1)
    exc = problem(f"{padding} {URL}")
    assert exc.code == "message_too_long"
    assert "201" in exc.message
    assert "200" in exc.message


def test_missing_link_is_rejected() -> None:
    exc = problem("No link in this message at all")
    assert exc.code == "link_count"
    assert "none was found" in exc.message


def test_two_links_are_rejected() -> None:
    exc = problem("Two links https://a.example.com and https://b.example.com")
    assert exc.code == "link_count"
    assert "2 were found" in exc.message


def test_duplicate_link_counts_as_two() -> None:
    exc = problem("Same link twice https://example.com https://example.com")
    assert exc.code == "link_count"


def test_non_http_link_is_not_a_cta_link() -> None:
    exc = problem("FTP link ftp://example.com/file")
    assert exc.code == "link_count"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/post",
        "http://127.0.0.1/post",
        "http://10.0.0.5/post",
        "http://192.168.1.20/post",
        "http://example",
        "http://example.c",
        "https://user:pass@example.com/post",
        "http://example.com:notaport/post",
    ],
)
def test_invalid_urls_are_rejected(url: str) -> None:
    exc = problem(f"Read this now {url}")
    assert exc.code == "invalid_url", exc.message


def test_trailing_punctuation_is_stripped() -> None:
    urls = extract_urls("Visit (https://example.com). Thanks!")
    assert urls == ["https://example.com"]


def test_markdown_style_url_is_detected() -> None:
    assert extract_urls("see https://example.com/path?q=1, thanks") == [
        "https://example.com/path?q=1"
    ]


def test_whitespace_is_normalised() -> None:
    assert normalize_message("  hello \n\n world  ") == "hello world"


def test_zero_width_space_is_removed() -> None:
    assert normalize_message("he\u200bllo") == "hello"


def test_whitespace_only_message_is_rejected() -> None:
    exc = problem("   \n\t  ")
    assert exc.code == "message_empty"


def test_unicode_message_is_counted_in_characters() -> None:
    text = "🚀 Launch day! " + "é" * 20 + " " + URL
    parsed = parse_message(text, max_length=200)
    assert parsed.url == URL


def test_normalised_message_is_returned() -> None:
    parsed = parse_message(f"  Hello   world  {URL}  ", max_length=200)
    assert parsed.text == f"Hello world {URL}"


def test_title_is_derived_without_the_link() -> None:
    parsed = parse_message(f"Big news for our platform. {URL}", max_length=200)
    assert parsed.title == "Big news for our platform"


def test_title_falls_back_when_message_is_only_a_link() -> None:
    parsed = parse_message(URL, max_length=200)
    assert parsed.title == "New update"


def test_title_is_truncated() -> None:
    title = derive_title("word " * 40 + URL, URL, limit=20)
    assert len(title) <= 20
    assert title.endswith("…")
