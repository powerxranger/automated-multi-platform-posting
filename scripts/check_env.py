"""Print a readiness table for every platform integration.

Usage:
    python scripts/check_env.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.config import PLATFORM_IDS, Settings  # noqa: E402
from app.platforms.registry import build_registry  # noqa: E402


def main() -> int:
    settings = Settings()
    client = httpx.AsyncClient()
    adapters = build_registry(settings, client)

    print("Platform readiness")
    print("-" * 78)
    print(f"{'platform':<18}{'id':<12}{'status':<18}missing / notes")
    print("-" * 78)

    ready = 0
    for adapter in adapters:
        if adapter.is_configured():
            ready += 1
            status = "ready"
            note = ""
        else:
            status = "not configured"
            note = ", ".join(adapter.missing_settings())
        print(f"{adapter.platform_name:<18}{adapter.platform_id:<12}{status:<18}{note}")

    print("-" * 78)
    print(f"{ready} of {len(PLATFORM_IDS)} platforms ready.")
    if settings.enabled_platform_ids is not None:
        print(f"ENABLED_PLATFORMS={sorted(settings.enabled_platform_ids)}")
    print(f"Timezone: {settings.app_timezone}")
    print(f"Public access verification: {'on' if settings.public_check_enabled else 'off'}")

    unknown = settings.enabled_platform_ids
    if unknown:
        unknown -= {adapter.platform_id for adapter in adapters}
        if unknown:
            print(f"WARNING: unknown ids in ENABLED_PLATFORMS: {sorted(unknown)}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
