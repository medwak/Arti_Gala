"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    database_url: str = "sqlite:///./arti_gala.db"
    # Shared secret partners use to sign pushes to POST /webhooks/inbound.
    inbound_webhook_secret: str | None = None
    # Outbound webhooks to localhost/private networks are blocked unless enabled (SSRF guard).
    allow_private_webhook_targets: bool = False
    webhook_max_attempts: int = 3
    webhook_timeout_seconds: float = 10.0
    user_agent: str = "ArtiGalaBot/0.1 (+https://github.com/medwak/arti_gala)"
    http_timeout_seconds: float = 30.0
    scrape_delay_seconds: float = 1.0
    smithsonian_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            database_url=env.get("ARTI_DATABASE_URL", cls.database_url),
            inbound_webhook_secret=env.get("ARTI_INBOUND_WEBHOOK_SECRET") or None,
            allow_private_webhook_targets=_bool(env.get("ARTI_ALLOW_PRIVATE_WEBHOOK_TARGETS")),
            webhook_max_attempts=int(env.get("ARTI_WEBHOOK_MAX_ATTEMPTS", cls.webhook_max_attempts)),
            webhook_timeout_seconds=float(env.get("ARTI_WEBHOOK_TIMEOUT", cls.webhook_timeout_seconds)),
            user_agent=env.get("ARTI_USER_AGENT", cls.user_agent),
            http_timeout_seconds=float(env.get("ARTI_HTTP_TIMEOUT", cls.http_timeout_seconds)),
            scrape_delay_seconds=float(env.get("ARTI_SCRAPE_DELAY", cls.scrape_delay_seconds)),
            smithsonian_api_key=env.get("ARTI_SMITHSONIAN_API_KEY") or None,
        )
