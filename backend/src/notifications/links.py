"""Signed links that do one thing without signing in: pausing a subscription."""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import re

LINK_DAYS = 365
_ACTION = "pause"  # part of what is signed: the signature is for nothing else
_TOKEN = re.compile(r"(0|[1-9][0-9]{0,17})\.([1-9][0-9]{0,11})\.([A-Za-z0-9_-]{43})")


def _sign(secret: str, identifier: str, expires: str) -> str:
    digest = hmac.new(secret.encode(), f"{_ACTION}.{identifier}.{expires}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def pause_token(secret: str, subscription_id: int, *, now: datetime.datetime | None = None) -> str:
    if not secret:
        raise ValueError("a secret is needed to sign links")
    now = now or datetime.datetime.now(datetime.UTC)
    expires = str(int((now + datetime.timedelta(days=LINK_DAYS)).timestamp()))
    return f"{subscription_id}.{expires}.{_sign(secret, str(subscription_id), expires)}"


def read_pause_token(secret: str, token: str, *, now: datetime.datetime | None = None) -> int | None:
    """The subscription that the token pauses, or None if it is not valid."""
    match = _TOKEN.fullmatch(token)
    if not secret or match is None:
        return None
    identifier, expires, signature = match.groups()
    if not hmac.compare_digest(signature, _sign(secret, identifier, expires)):
        return None
    now = now or datetime.datetime.now(datetime.UTC)
    return int(identifier) if now.timestamp() < int(expires) else None
