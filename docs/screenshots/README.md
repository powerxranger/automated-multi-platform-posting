# Demo evidence

Screenshots and captured logs that prove the integrations are real belong here.

## Required before submission

| File | What to capture |
|---|---|
| `01-swagger.png` | `http://localhost:4000/docs` with the `POST /posting` example body visible |
| `02-platforms.png` | `GET /platforms` showing every adapter `"configured": true` |
| `03-posting-response.png` | The `200` response from `POST /posting` in `/docs` or Postman |
| `04-bluesky.png` | The published Bluesky post open in a browser, URL bar visible |
| `05-mastodon.png` | The published Mastodon status open in a browser |
| `06-telegram.png` | The published message in the public channel |
| `07-github-issue.png` | The public GitHub issue |
| `08-gist.png` | The public gist |
| `09-partial-failure.png` | *(Optional)* One platform deliberately misconfigured, others still succeeding |
| `10-tests.png` | `pytest --cov=app` output (all green, coverage percentage visible) |
| `11-ci.png` | Green GitHub Actions run |

## Rules

- One browser screenshot per platform is worth more than any prose.
- Never edit a screenshot to imply a post that does not exist.
- If a platform is unavailable, capture the honest `failed` / `unavailable` row instead of hiding it.
- Full captured JSON responses go next to this folder in `sample_responses/`.
