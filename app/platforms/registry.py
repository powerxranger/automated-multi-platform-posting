"""Adapter registry - reliability-ordered, so the default run always has
guaranteed-working platforms first and approval-gated ones last.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.platforms.base import PlatformAdapter
from app.platforms.bluesky import BlueskyAdapter
from app.platforms.devto import DevToAdapter
from app.platforms.github_gist import GitHubGistAdapter
from app.platforms.hashnode import HashnodeAdapter
from app.platforms.linkedin import LinkedInAdapter
from app.platforms.mastodon import MastodonAdapter
from app.platforms.reddit import RedditAdapter
from app.platforms.telegram import TelegramAdapter
from app.platforms.x_twitter import XAdapter

#: Order matters: it is the order results are returned in, and it goes from
#: "credentials available instantly, no approval" to "approval required".
ADAPTER_TYPES: tuple[type[PlatformAdapter], ...] = (
    BlueskyAdapter,
    MastodonAdapter,
    TelegramAdapter,
    DevToAdapter,
    GitHubGistAdapter,
    LinkedInAdapter,
    XAdapter,
    RedditAdapter,
    HashnodeAdapter,
)


def build_registry(settings: Settings, client: httpx.AsyncClient) -> list[PlatformAdapter]:
    return [adapter_type(settings, client) for adapter_type in ADAPTER_TYPES]
