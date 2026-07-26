"""Read-only production launch validation.

Run with ``python -m src.launch_preflight`` before enabling the bot.
The command never prints credential values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def check_environment(
    environment: Mapping[str, str],
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Return human-readable blockers without making network calls."""
    errors: list[str] = []
    root = project_root or Path.cwd()
    database_url = environment.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        errors.append("DATABASE_URL must use PostgreSQL")
    if environment.get("FANSLY_PROVIDER", "").lower() != "fanslyapi":
        errors.append("FANSLY_PROVIDER must be fanslyapi")
    api_key = environment.get("FANSLY_API_KEY", "").strip()
    if not api_key or api_key == "your_api_key_here":
        errors.append("FANSLY_API_KEY is not configured")
    if not environment.get("DASHBOARD_USER", "").strip():
        errors.append("DASHBOARD_USER is not configured")
    if len(environment.get("DASHBOARD_PASSWORD", "")) < 16:
        errors.append("DASHBOARD_PASSWORD must be at least 16 characters")

    controlled = _enabled(
        environment.get("CONTROLLED_LAUNCH"),
        default=True,
    )
    allowlist = {
        value.strip()
        for value in environment.get("FAN_ALLOWLIST", "").split(",")
        if value.strip()
    }
    if controlled and not allowlist:
        errors.append("FAN_ALLOWLIST must contain at least one pilot fan")
    if _enabled(
        environment.get("BOT_ENABLED_DEFAULT"),
        default=False,
    ):
        errors.append("BOT_ENABLED_DEFAULT must remain false for launch")

    creator_id = environment.get("CREATOR_ID", "sunny_charm")
    configured_dir = Path(
        environment.get("PERSONA_DIR", "config/creators")
    )
    if not configured_dir.is_absolute():
        configured_dir = root / configured_dir
    candidates = (
        configured_dir / f"{creator_id}.yaml",
        root / "config" / "creators" / f"{creator_id}.yaml",
    )
    if not any(candidate.exists() for candidate in candidates):
        errors.append(f"persona YAML is missing for creator {creator_id}")
    return errors


def main() -> int:
    errors = check_environment(os.environ)
    if errors:
        print("Launch preflight: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Launch preflight: PASS")
    print("No credentials were printed and no external calls were made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
