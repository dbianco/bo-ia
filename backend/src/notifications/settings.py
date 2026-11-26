"""Settings of the notifications: from the environment and the installation."""
from __future__ import annotations

import os
from dataclasses import dataclass

from src.config.installation import InstallationConfig

DEFAULT_DIGEST_HOUR = 7
DEFAULT_MAX_RETRIES = 48  # with up to an hour between them, some two days


class NotificationSettingsError(ValueError):
    """A setting is not valid: the service must not start with it."""


@dataclass(frozen=True)
class NotificationSettings:
    installation: str
    filter_labels: dict[str, str]
    timezone: str
    digest_hour: int
    public_url: str  # of the web, for the links of the emails; empty: no links
    link_secret: str  # signs them; empty: no links
    max_retries: int

    @property
    def has_links(self) -> bool:
        return bool(self.public_url and self.link_secret)


def link_secret() -> str:
    return os.environ.get("LINK_SECRET", "").strip()


def _whole_number(name: str, default: int, low: int, high: int) -> int:
    text = os.environ.get(name, "").strip()
    if not text:
        return default
    if not text.isdecimal() or not low <= int(text) <= high:
        raise NotificationSettingsError(f"{name} must be a whole number from {low} to {high}, not {text!r}")
    return int(text)


def settings_from_environment(installation: InstallationConfig) -> NotificationSettings:
    url = os.environ.get("PUBLIC_WEB_URL", "").strip().rstrip("/")
    if url and not url.startswith(("https://", "http://")):
        raise NotificationSettingsError(f"PUBLIC_WEB_URL must start with https:// or http://, not {url!r}")
    return NotificationSettings(
        installation=installation.nombre,
        filter_labels={f.clave: f.etiqueta for f in installation.filtros},
        timezone=installation.timezone,
        digest_hour=_whole_number("DIGEST_HOUR", DEFAULT_DIGEST_HOUR, 0, 23),
        public_url=url,
        link_secret=link_secret(),
        max_retries=_whole_number("EMAIL_MAX_RETRIES", DEFAULT_MAX_RETRIES, 0, 10_000),
    )
