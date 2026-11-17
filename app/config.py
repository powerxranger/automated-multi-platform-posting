"""Typed application configuration.

All credentials are optional. A platform adapter reports itself as "unavailable"
when its credentials are absent, so the service keeps working with whatever is
configured locally.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PLATFORM_IDS: tuple[str, ...] = (
    "bluesky",
    "mastodon",
    "telegram",
    "github_issue",
    "gist",
)


class Settings(BaseSettings):
    """Environment-driven settings (see `.env.example`)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------------------------------------------- app ----
    app_name: str = "Automated Multi-Platform Posting"
    app_version: str = "1.0.0"
    environment: str = "local"
    log_level: str = "INFO"
    app_timezone: str = "Asia/Kolkata"
    user_agent: str = "automated-posting/1.0 (+https://github.com/powerxranger)"
    max_message_length: int = Field(default=200, ge=1, le=10_000)

    # --------------------------------------------------------- reliability ---
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    max_concurrent_platforms: int = Field(default=5, ge=1, le=20)
    max_retries: int = Field(default=1, ge=0, le=3)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=10)

    # ------------------------------------------------------- public access ---
    public_check_enabled: bool = True
    public_check_timeout_seconds: float = Field(default=8.0, gt=0, le=60)

    # --------------------------------------------------------- idempotency ---
    idempotency_ttl_seconds: int = Field(default=600, ge=0, le=86_400)

    # ------------------------------------------------------------ selection --
    enabled_platforms: str = ""

    # -------------------------------------------------------------- bluesky --
    bluesky_handle: str | None = None
    bluesky_app_password: str | None = None
    bluesky_pds_url: str = "https://bsky.social"

    # ------------------------------------------------------------- mastodon --
    mastodon_instance_url: str | None = None
    mastodon_access_token: str | None = None
    mastodon_visibility: str = "public"

    # ------------------------------------------------------------- telegram --
    telegram_bot_token: str | None = None
    telegram_channel: str | None = None

    # --------------------------------------------------------- github issue --
    # Optional separate token. Falls back to GITHUB_TOKEN when unset, so the
    # Issues write permission can be granted without widening the Gist token.
    github_issue_token: str | None = None
    github_issue_repo: str = "powerxranger/automated-multi-platform-posting"

    # ----------------------------------------------------------------- gist --
    github_token: str | None = None
    github_gist_public: bool = True

    # ------------------------------------------------------------- helpers ---
    @property
    def enabled_platform_ids(self) -> set[str] | None:
        """Platforms explicitly enabled via `ENABLED_PLATFORMS`.

        Returns `None` when the variable is empty, meaning "use everything that
        is configured". Unknown ids are ignored silently by the registry.
        """
        raw = (self.enabled_platforms or "").strip()
        if not raw:
            return None
        return {part.strip().lower() for part in raw.split(",") if part.strip()}

    @property
    def all_secrets(self) -> list[str]:
        """Every credential value, used to redact log output."""
        candidates = [
            self.bluesky_app_password,
            self.mastodon_access_token,
            self.telegram_bot_token,
            self.github_token,
            self.github_issue_token,
        ]
        return [value for value in candidates if value and len(value) >= 6]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
