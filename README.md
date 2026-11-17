# Automated Multi-Platform Posting System

Built for the Dxora Technologies practical test.

I built this around one small request: `POST /posting` with a message. The service checks the message once, then posts it to five platforms. If one account is broken, the other four still go out. That was the part I cared about most, no fake "all succeeded" responses.

[![ci](https://github.com/powerxranger/automated-multi-platform-posting/actions/workflows/ci.yml/badge.svg)](https://github.com/powerxranger/automated-multi-platform-posting/actions/workflows/ci.yml)
![tests](https://img.shields.io/badge/tests-99%20passing-success)
![coverage](https://img.shields.io/badge/coverage-93%25-success)
![license](https://img.shields.io/badge/license-MIT-blue)

```
POST http://localhost:4000/posting
{ "message": "Check out our latest business platform ... https://example.com" }
```

---

## Start here

Requires Python 3.11+.

```bash
git clone https://github.com/powerxranger/automated-multi-platform-posting.git
cd automated-multi-platform-posting

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
cp .env.example .env            # Windows: Copy-Item .env.example .env
```

Fill in the five sets of credentials in `.env`, then start the server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

Open **http://localhost:4000/docs** and try `POST /posting`. The body is just:

```json
{ "message": "Check out our latest business platform and grow your online visibility. https://example.com" }
```

Before publishing anything real, it is worth checking what the app sees:

```bash
python scripts/check_env.py
curl http://localhost:4000/platforms
```

Docker is there too if you prefer it: `docker compose up --build`.

---

## What the endpoint actually does

- Trims the message and counts characters. The limit is 200.
- Requires exactly one link. Zero or two links are rejected.
- Checks that link properly: `http`/`https`, real hostname and TLD, no embedded credentials, no private or loopback address, valid port.
- Keeps platform selection on the server. The caller does **not** send a `platforms` field; sending one gets a `422`.
- Posts to five platforms at the same time, with a 15-second timeout per platform.
- Retries once, but only for transient problems: `429`, `5xx`, timeout, connection error. A bad token is not retried.
- Returns one row per platform with `platform`, `status`, `posted_url`, `public_access`, `date`, `time` and `error`.
- Verifies `public_access` with an anonymous GET after publishing. It is not just set to `true` because the API call returned `200`.

The five platforms are **Bluesky, Mastodon, Telegram, Dev.to and GitHub Gist**. I picked these because all five can publish text and give back a public URL without an app review.

If no credentials are configured, the endpoint returns `503 NO_PLATFORMS_CONFIGURED` and lists what is missing. It never invents a success.

---

## How a request flows

```
POST /posting
  -> Pydantic: message is a string, extra fields are rejected
  -> validation: length, one CTA link, URL policy
  -> PostingService
       -> five adapters in parallel (asyncio.gather)
       -> timeout + retry per platform
       -> anonymous GET of the posted URL
  -> one result row per platform
```

Adapters only know their own API. The service owns retries, timeouts and aggregation. That separation is deliberate: a broken Bluesky adapter cannot stop Mastodon, and every rule can be tested without touching the network.

Default reliability settings:

| Setting | Value |
|---|---|
| Per-platform timeout | 15 seconds |
| Concurrent posts | 5 |
| Retries | 1, transient failures only |
| Backoff | exponential with jitter, honours `Retry-After` up to 3 seconds |

---

## Config you may care about

| Variable | Purpose | Default |
|---|---|---|
| `APP_TIMEZONE` | Timezone used for `date` / `time` | `Asia/Kolkata` |
| `ENABLED_PLATFORMS` | Comma-separated ids to use; empty means all configured | *(empty)* |
| `REQUEST_TIMEOUT_SECONDS` | Per-platform deadline | `15` |
| `MAX_CONCURRENT_PLATFORMS` | Parallel posts | `5` |
| `MAX_RETRIES` | Retries for transient failures only | `1` |
| `PUBLIC_CHECK_ENABLED` | Verify posted URLs anonymously | `true` |
| `IDEMPOTENCY_TTL_SECONDS` | `Idempotency-Key` cache lifetime | `600` |

`.env.example` has the full annotated list. `ENABLED_PLATFORMS` is the only way to change the platform set, and it is server-side. It is not a request field.

---

## Getting the five credentials

| Platform | Auth | Public URL shape | What you need |
|---|---|---|---|
| Bluesky | `createSession` → JWT | `bsky.app/profile/{handle}/post/{rkey}` | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` |
| Mastodon | Bearer token | `{instance}/@{user}/{id}` | `MASTODON_INSTANCE_URL`, `MASTODON_ACCESS_TOKEN` |
| Telegram | Bot token, admin of a public channel | `t.me/{channel}/{message_id}` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL` |
| Dev.to | `api-key` header | `dev.to/{user}/{slug}` | `DEVTO_API_KEY` |
| GitHub Gist | Fine-grained PAT | `gist.github.com/...` | `GITHUB_TOKEN` |

Short version of each:

1. **Bluesky** — bsky.app → *Settings* → *App Passwords* → add one. Use an app password, not your account password. No approval needed.
2. **Mastodon** — *Preferences* → *Development* → *New application*, scope `write:statuses`. Put the exact instance URL with `https://` in `MASTODON_INSTANCE_URL`.
3. **Telegram** — `@BotFather` → `/newbot`. Make a **public** channel with a username, then add the bot as an administrator with *Post Messages*. `TELEGRAM_CHANNEL` accepts `@name`, `name` or `https://t.me/name`.
4. **Dev.to** — *Settings* → *Extensions* → *DEV Community API Keys* → generate. Each article needs a unique CTA link because it is sent as the canonical URL.
5. **GitHub Gist** — *Settings* → *Developer settings* → *Personal access tokens* → **fine-grained**, with **Account permissions → Gists: read and write**.

I did not add more platforms for the sake of a bigger number. Medium shut down its public write API; Threads, Pinterest and Facebook need app review; Slack and Discord posts are not publicly readable; Buffer and Ayrshare are aggregators, not direct integrations.

---

## API

### `POST /posting`

| | |
|---|---|
| Body | `{"message": string}` — extra fields are rejected with `422` |
| Optional header | `Idempotency-Key: <string>` — same key within 10 minutes returns the cached response |
| `200` | At least one platform published. `success` is `true`, `summary` has the detail |
| `422` | Validation failed, with a structured `fields[]` array |
| `503` | No platform configured |
| `500` | Unexpected server error, without leaking internals |

Each row in `results` has the requested flat fields, plus a small `meta` object with `http_status`, `latency_ms`, `attempts`, `public_access_verified`, `timezone`, `post_id` and `checked_at_utc`.

### Other endpoints

| Endpoint | Why it is there |
|---|---|
| `GET /health` | Liveness plus how many platforms are configured |
| `GET /platforms` | Readiness report: configured, enabled, missing variables |
| `POST /validate` | Dry run of the rules, no publishing |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | Interactive docs |

---

## Validation rules

Applied after whitespace normalisation, in this order.

| Rule | Failure code | Example detail |
|---|---|---|
| Not empty | `message_empty` | `Message must not be empty.` |
| ≤ 200 characters | `message_too_long` | `Message is 231 characters; the maximum is 200.` |
| Exactly one link | `link_count` | `Exactly one CTA link is required; none was found.` |
| `http` or `https` only | `invalid_url` | `only http and https URLs are supported.` |
| Hostname has a TLD | `invalid_url` | `'example' is not a valid top-level domain` |
| No embedded credentials | `invalid_url` | `credentials embedded in the URL are not allowed` |
| No private / loopback host | `invalid_url` | `private or reserved IP addresses are not publicly reachable` |
| Valid port | `invalid_url` | `the URL contains an invalid port` |

Trailing punctuation is stripped, so `(https://example.com).` is read as `https://example.com`. Counting is by Unicode code point.

---

## Proof from a real run

This was an actual `POST /posting` call against the five configured accounts, not a fixture. Full response: [`docs/sample_responses/live-run.json`](docs/sample_responses/live-run.json).

```
HTTP 200
success: true
summary: 5 total / 5 succeeded / 0 failed / 2314 ms / 0 unavailable
```

| Platform | Status | URL | public_access |
|---|---|---|---|
| Bluesky | success | https://bsky.app/profile/aggarwalkrish28.bsky.social/post/3n2ixqpgxq22f | true, verified |
| Mastodon | success | https://mastodon.social/@aggarwalkrish28/117631609179418319 | true, verified |
| Telegram | success | https://t.me/aggarchannel/5 | true, verified |
| Dev.to | success | https://dev.to/krish_aggarwal_6e08a24f75/final-five-platform-verification-run-2932 | true, verified |
| GitHub Gist | success | https://gist.github.com/powerxranger/efe18d15fc21cf8fcd905690bd452ae7 | true, verified |

Abridged response:

```json
{
  "success": true,
  "request_id": "0f055c3229f144498669f1fc63a3ad78",
  "message": "Final five platform verification run https://example.com/final5-171510",
  "summary": { "total": 5, "succeeded": 5, "failed": 0, "duration_ms": 2314, "platforms_unavailable": [] },
  "results": [
    {
      "platform": "Telegram",
      "status": "success",
      "posted_url": "https://t.me/aggarchannel/5",
      "public_access": true,
      "date": "2026-11-17",
      "time": "17:15:11",
      "error": null,
      "meta": { "http_status": 200, "latency_ms": 1263, "attempts": 1,
                "public_access_verified": true, "timezone": "Asia/Kolkata" }
    }
  ],
  "replayed": false
}
```

Two error shapes from test runs:

```console
$ curl -s -X POST http://localhost:4000/posting -H "Content-Type: application/json" \
    -d '{"message":"no link"}'
{"success":false,"request_id":"c96bede6f094455382ba6db681347ec1",
 "error":{"code":"VALIDATION_ERROR",
          "message":"The request body is invalid. See the fields array for details.",
          "fields":[{"field":"message","code":"link_count",
                     "detail":"Exactly one CTA link is required; none was found."}]}}
```

```console
$ curl -s -X POST http://localhost:4000/posting -H "Content-Type: application/json" \
    -d '{"message":"Check out our platform https://example.com"}'
{"success":false,"request_id":"f8179d77dd62436e8af575a04eb76670",
 "error":{"code":"NO_PLATFORMS_CONFIGURED",
          "message":"No platform is configured. Fill in at least one set of credentials in .env (see .env.example) and restart the server."}}
```

More ready-to-run requests: [`requests.http`](requests.http) and [`docs/postman_collection.json`](docs/postman_collection.json). The screenshot checklist is in [`docs/screenshots/README.md`](docs/screenshots/README.md).

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest --cov=app --cov-report=term-missing
```

```
99 passed
TOTAL   832 statements   38 missed   93% coverage
```

The suite makes no network calls. `httpx.MockTransport` stands in for every API.

- **Validation (25):** 200 vs 201 characters, zero/one/two links, duplicate links, `ftp://`, localhost, private IPs, missing TLD, embedded credentials, bad port, trailing punctuation, unicode, title derivation.
- **Orchestration (16):** all succeed, one fails while the rest still publish, all fail, unavailable platforms, `ENABLED_PLATFORMS`, retryable vs non-retryable errors, retry counting, timeout isolation, real parallelism, idempotency replay, public-access verification.
- **Adapters (25):** request payload shape per platform, including Bluesky's UTF-8 byte offsets, URL construction, `401/403/404/422/429/500` mapping, `Retry-After`, timeouts, non-JSON replies, Telegram `ok:false` and `t.me/` URLs.
- **HTTP contract (22):** status codes, error envelope, `extra_forbidden`, malformed JSON, `X-Request-ID` echo, 404 envelope, OpenAPI content, no credentials in responses.
- **Security and public access (11):** token redaction in logs, errors and responses; anonymous GET login-wall detection.

CI runs `ruff check`, `ruff format --check`, `mypy app` and the suite with `--cov-fail-under=90` on Python 3.11 and 3.12. The latest run is green.

---

## Choices I made on purpose

1. **Platform selection is server-side.** The brief said selection is internal, so `platforms` is not a request field. Operators use `ENABLED_PLATFORMS`.
2. **Partial success returns `200`.** The goal is to publish where possible. A `5xx` would make retries ambiguous, so `success` means at least one platform published and `summary` tells the rest of the story.
3. **Only transient failures are retried.** `429`, `5xx`, timeouts and connection errors get one more try. `401`, `403` and `422` fail the same way the second time, so retrying them is just noise.
4. **`public_access` is checked.** A successful post can still be deleted or sit behind a login wall. The app fetches the URL without credentials before saying it is public.
5. **No link reachability check in the hot path.** That lives in `POST /validate`, so publishing is not slowed down by the destination site.
6. **Idempotency is a header.** `Idempotency-Key` protects against double-clicks in `/docs` without changing the required body schema.
7. **Adapters raise, the service decides.** Retry, timeout and aggregation rules stay in one place.

---

## Errors you will see

| Code | Meaning | Retried |
|---|---|---|
| `auth_failed` | `401`/`403`, bad or expired credentials | no |
| `rate_limited` | `429`, honours `Retry-After` up to 3 seconds | yes |
| `timeout` | Per-platform deadline exceeded | yes |
| `network` | Connection error or `5xx` | yes |
| `platform_rejected` | Other 4xx or a platform-specific rejection | no |
| `unexpected` | Malformed response or broken adapter contract | no |
| `config_missing` | Credentials absent, platform skipped rather than failed | — |

Response-level codes: `VALIDATION_ERROR` (`422`), `NO_PLATFORMS_CONFIGURED` (`503`), `HTTP_404`, `INTERNAL_ERROR` (`500`). Every response echoes `X-Request-ID`.

---

## Secrets

- Credentials come from environment variables only. `.env` has been gitignored from the first commit.
- A redaction filter registers configured secrets and scrubs them from logs, adapter errors and HTTP responses. There are tests for this.
- `.pre-commit-config.yaml` includes `gitleaks` and `detect-private-key`.
- Posting is deliberately low-volume: one post per platform per request, no loops, no scheduler.
- The Docker image runs as a non-root user.

---

## What I left out

- **No persistence.** Idempotency keys live in memory, so a restart forgets them and there is no post history. A production version would use Redis or DynamoDB plus a `posting_events` table.
- **No queue.** The caller waits for the slowest platform. A production version would enqueue per-platform jobs and return `202` with a status URL.
- **No circuit breaker.** A consistently failing platform still costs one attempt per request.
- **Dev.to canonical URLs must be unique**, so each post needs a different CTA link.
- **No media, threads or scheduling.** The brief asked for text-only, single, immediate posts, so that is what this does.

---

## Layout

```
app/
├── main.py                  # app factory, lifespan, handlers, request-id middleware
├── api/routes.py            # /posting, /platforms, /health, /validate
├── schemas.py               # Pydantic request/response models
├── config.py                # typed settings
├── errors.py                # error taxonomy and HTTP mapping
├── logging.py               # JSON logs with secret redaction
├── platforms/
│   ├── base.py              # PlatformAdapter contract and HTTP helper
│   ├── registry.py          # the five adapters, in result order
│   └── bluesky.py · mastodon.py · telegram.py · devto.py · github_gist.py
└── services/
    ├── posting_service.py   # concurrency, timeouts, retries, idempotency
    ├── url_validator.py     # pure validation rules
    └── public_access.py     # anonymous reachability check

tests/           99 tests, no network
scripts/         check_env.py · smoke_test.py
docs/            postman_collection.json · sample_responses/ · screenshots/
```

---

## License

MIT — see [LICENSE](LICENSE).
