"""End-to-end smoke test against a running server.

Start the API first:
    uvicorn app.main:app --host 0.0.0.0 --port 4000

Then:
    python scripts/smoke_test.py "Your message https://example.com"
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

DEFAULT_MESSAGE = (
    "Check out our latest business platform and grow your online visibility. https://example.com"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the posting API.")
    parser.add_argument("message", nargs="?", default=DEFAULT_MESSAGE)
    parser.add_argument("--base-url", default="http://localhost:4000")
    parser.add_argument("--dry-run", action="store_true", help="Only call /validate")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=90) as client:
        health = client.get("/health")
        print("GET /health ->", health.status_code, json.dumps(health.json(), indent=2))

        platforms = client.get("/platforms")
        ready = [
            item["platform"]
            for item in platforms.json()["platforms"]
            if item["configured"] and item["enabled"]
        ]
        print("\nConfigured platforms:", ", ".join(ready) or "none")
        if not ready:
            print("Nothing to publish to. Fill in .env first.")
            return 1

        validation = client.post("/validate", json={"message": args.message})
        print("\nPOST /validate ->", validation.status_code)
        print(json.dumps(validation.json(), indent=2))
        if not validation.json()["valid"]:
            print("Message is invalid; not publishing.")
            return 1
        if args.dry_run:
            return 0

        response = client.post("/posting", json={"message": args.message})
        print("\nPOST /posting ->", response.status_code)
        print(json.dumps(response.json(), indent=2))
        return 0 if response.json().get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
