"""Structured JSON logging with secret redaction.

Every log line is a single JSON object that carries the request id, which makes
the output greppable and safe to paste into a README screenshot.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_redactions: list[str] = []
_MAX_REDACTIONS = 64


def register_secret(value: str | None) -> None:
    """Register a credential so it can never appear in logs or responses."""
    if not value or len(value) < 6:
        return
    if value in _redactions:
        return
    _redactions.append(value)
    _redactions.sort(key=len, reverse=True)
    del _redactions[_MAX_REDACTIONS:]


def register_secrets(values: list[str] | tuple[str, ...]) -> None:
    for value in values:
        register_secret(value)


def redact(text: str) -> str:
    """Replace every registered credential with `***`."""
    cleaned = text
    for secret in _redactions:
        cleaned = cleaned.replace(secret, "***")
    return cleaned


def reset_secrets() -> None:
    """Test helper: forget previously registered credentials."""
    _redactions.clear()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_ctx.get(),
            "event": redact(record.getMessage()),
        }
        data = getattr(record, "data", None)
        if isinstance(data, dict):
            for key, value in data.items():
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # httpx logs full URLs at INFO; keep third-party noise down.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
