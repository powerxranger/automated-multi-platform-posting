"""Telegram Bot API integration (sendMessage to a public channel).

The bot must be an administrator of a channel that has a public @username,
otherwise the resulting link is not publicly readable.

https://core.telegram.org/bots/api#sendmessage
"""

from __future__ import annotations

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome


class TelegramAdapter(PlatformAdapter):
    platform_id = "telegram"
    platform_name = "Telegram"
    required_settings = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL")

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        token = self.settings.telegram_bot_token
        channel = str(self.settings.telegram_channel or "").strip()
        if not channel.startswith("@"):
            channel = f"@{channel.lstrip('@')}"

        response = await self.send(
            "POST",
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": channel,
                "text": message.text,
                "disable_web_page_preview": False,
            },
        )
        body = self.json_body(response)
        # Telegram signals logical failures with HTTP 200 + ok=false.
        if not body.get("ok"):
            raise PlatformError(
                ErrorCode.PLATFORM_REJECTED,
                f"Telegram rejected the message: {body.get('description', 'unknown error')}",
                http_status=response.status_code,
            )
        result = body.get("result") or {}
        message_id = result.get("message_id")
        if message_id is None:
            raise PlatformError(ErrorCode.UNEXPECTED, "Telegram did not return a message_id.")

        return PublishOutcome(
            posted_url=f"https://t.me/{channel.lstrip('@')}/{message_id}",
            post_id=str(message_id),
            http_status=response.status_code,
        )
