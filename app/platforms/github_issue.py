"""GitHub Issues integration (create a public issue in a repository).

https://docs.github.com/en/rest/issues/issues#create-an-issue

This is a separate product and URL shape from GitHub Gist, even though both
use the same GitHub token.
"""

from __future__ import annotations

from app.errors import ErrorCode, PlatformError
from app.platforms.base import ParsedMessage, PlatformAdapter, PublishOutcome

_BASE = "https://api.github.com/repos/{repo}/issues"


class GitHubIssueAdapter(PlatformAdapter):
    platform_id = "github_issue"
    platform_name = "GitHub Issue"
    required_settings = ("GITHUB_TOKEN", "GITHUB_ISSUE_REPO")

    def is_configured(self) -> bool:
        return not self.missing_settings()

    async def publish_once(self, message: ParsedMessage) -> PublishOutcome:
        repo = str(self.settings.github_issue_repo or "").strip().strip("/")
        if not repo or repo.count("/") != 1:
            raise PlatformError(
                ErrorCode.UNEXPECTED,
                "GITHUB_ISSUE_REPO must be in 'owner/repo' format.",
            )

        token = self.settings.github_issue_token or self.settings.github_token
        response = await self.send(
            "POST",
            _BASE.format(repo=repo),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": message.title, "body": message.text},
        )
        body = self.json_body(response)
        posted_url = body.get("html_url")
        if not posted_url or "/issues/" not in str(posted_url):
            raise PlatformError(ErrorCode.UNEXPECTED, "GitHub did not return an issue URL.")
        return PublishOutcome(
            posted_url=str(posted_url),
            post_id=str(body.get("number") or "") or None,
            http_status=response.status_code,
        )
