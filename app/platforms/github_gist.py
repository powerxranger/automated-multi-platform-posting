"""GitHub Gist integration (POST /gists) - a zero-friction public mirror.

Requires a fine-grained PAT with the "Gists" permission.

https://docs.github.com/en/rest/gists/gists#create-a-gist
"""

from __future__ import annotations

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome


class GitHubGistAdapter(PlatformAdapter):
    platform_id = "gist"
    platform_name = "GitHub Gist"
    required_settings = ("GITHUB_TOKEN",)

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        response = await self.send(
            "POST",
            "https://api.github.com/gists",
            headers={
                "Authorization": f"Bearer {self.settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "description": message.title,
                "public": self.settings.github_gist_public,
                "files": {"post.md": {"content": message.text}},
            },
        )
        body = self.json_body(response)
        posted_url = body.get("html_url")
        if not posted_url:
            raise PlatformError(ErrorCode.UNEXPECTED, "GitHub did not return a gist URL.")
        return PublishOutcome(
            posted_url=str(posted_url),
            post_id=str(body.get("id") or "") or None,
            http_status=response.status_code,
        )
