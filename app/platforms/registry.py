"""Adapter registry - reliability-ordered.

The service supports exactly five platforms, as specified by the brief. Every
adapter uses a different authentication mechanism and is independent of the
others.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.platforms.base import PlatformAdapter
from app.platforms.bluesky import BlueskyAdapter
from app.platforms.devto import DevToAdapter
from app.platforms.github_gist import GitHubGistAdapter
from app.platforms.mastodon import MastodonAdapter
from app.platforms.telegram import TelegramAdapter

#: Order matters: it is the order results are returned in.
ADAPTER_TYPES: tuple[type[PlatformAdapter], ...] = (
    BlueskyAdapter,
    MastodonAdapter,
    TelegramAdapter,
    DevToAdapter,
    GitHubGistAdapter,
)


def build_registry(settings: Settings, client: httpx.AsyncClient) -> list[PlatformAdapter]:
    return [adapter_type(settings, client) for adapter_type in ADAPTER_TYPES]
