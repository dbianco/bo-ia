"""Rate limit of the endpoints that anybody can call, by address.

Each group of endpoints has a limit such as `60/minute`, from the environment
(`RATE_LIMIT_SEARCH` and so on; `off` removes it). Counts are in the memory of
this process: they start again with it, and a second process would count apart.

An address may use its whole limit at once, and then gets one more call every
(period / limit)."""
from __future__ import annotations

import ipaddress
import math
import os
import re
import socket
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException, Request

DEFAULTS = {
    "search": "60/minute",  # each one costs an embedding
    "ratings": "30/minute",
    "register": "10/hour",
    "login": "10/minute",  # each one costs a password hash
    "public": "120/minute",  # the rest: configuration, issues, signing out, links of the emails
}
# What is not here requires a user or the operator, and has no limit.
GROUPS_BY_ROUTE = {
    ("GET", "/v1/search"): "search",
    ("POST", "/v1/valoraciones"): "ratings",
    ("POST", "/v1/auth/registro"): "register",
    ("POST", "/v1/auth/login"): "login",
    ("POST", "/v1/auth/logout"): "public",
    ("GET", "/v1/config"): "public",
    ("GET", "/v1/issues/{source}/{issue}"): "public",
    ("GET", "/v1/pause-links"): "public",
    ("POST", "/v1/pause-links"): "public",
}

PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
MAX_ADDRESSES = 100_000
NAME_SECONDS = 30  # how long the address of a proxy with a name is remembered


class RateLimitConfigError(ValueError):
    """A limit is not valid: the service must not start without it."""


@dataclass(frozen=True)
class Limit:
    count: int
    seconds: int


def parse_limit(text: str) -> Limit | None:
    """`60/minute`, or None for `off`."""
    if text.strip().lower() == "off":
        return None
    match = re.fullmatch(r"(\d+)\s*/\s*([a-z]+)", text.strip().lower())
    if match is None or match[2] not in PERIODS or int(match[1]) < 1:
        raise RateLimitConfigError(f"{text!r} is not a limit: use a number and a period, such as 60/minute, or off")
    return Limit(int(match[1]), PERIODS[match[2]])


def variable(group: str) -> str:
    return f"RATE_LIMIT_{group.upper()}"


def load_limits() -> dict[str, Limit | None]:
    limits = {}
    for group, default in DEFAULTS.items():
        text = os.environ.get(variable(group), "").strip() or default
        try:
            limits[group] = parse_limit(text)
        except RateLimitConfigError as exc:
            raise RateLimitConfigError(f"{variable(group)}: {exc}") from exc
    return limits


class RateLimiter:
    def __init__(
        self,
        limits: Mapping[str, Limit | None] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_addresses: int = MAX_ADDRESSES,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._max_addresses = max_addresses
        self._lock = threading.Lock()
        # When the limit of each caller will be whole again, the oldest first.
        self._whole_at: OrderedDict[tuple[str, str], float] = OrderedDict()

    def __len__(self) -> int:
        return len(self._whole_at)

    def reset(self) -> None:
        """Forgets the calls, and reads the environment again."""
        with self._lock:
            self._limits = None
            self._whole_at.clear()

    def wait(self, group: str, address: str) -> float:
        """Counts a call: 0 if it may go on, or how many seconds to wait (and then
        it does not count)."""
        with self._lock:
            if self._limits is None:
                self._limits = load_limits()
            limit = self._limits[group]
            if limit is None:
                return 0.0
            now, key = self._clock(), (group, address)
            step = limit.seconds / limit.count
            whole_at = max(self._whole_at.get(key, now), now)
            # The limit is `count` steps; each call takes one, and time gives them back.
            wait = whole_at + step - (now + limit.seconds)
            if wait > 1e-9:
                return wait
            self._whole_at[key] = whole_at + step
            self._whole_at.move_to_end(key)
            while len(self._whole_at) > self._max_addresses:
                self._whole_at.popitem(last=False)
            return 0.0


limiter = RateLimiter()


def resolve_name(name: str) -> set[str]:
    try:
        return {str(info[4][0]) for info in socket.getaddrinfo(name, None)}
    except OSError:
        return set()


@lru_cache(maxsize=64)
def _resolved(name: str, moment: int) -> frozenset[str]:
    return frozenset(resolve_name(name))


def _resolve(name: str) -> frozenset[str]:
    return _resolved(name, int(time.monotonic() // NAME_SECONDS))


def _address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    text = text.strip()
    if text.startswith("["):  # [2001:db8::1]:443
        text = text[1:].partition("]")[0]
    elif text.count(":") == 1:  # 1.2.3.4:5678
        text = text.partition(":")[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    return getattr(address, "ipv4_mapped", None) or address


def _is_trusted(address, trusted: list[str], resolve: Callable[[str], set[str] | frozenset[str]]) -> bool:
    for item in trusted:
        try:
            if address in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:  # it is a name
            if str(address) in resolve(item):
                return True
    return False


def client_address(
    peer: str | None,
    forwarded: str | None,
    trusted: str,
    *,
    resolve: Callable[[str], set[str] | frozenset[str]] = _resolve,
) -> str:
    """Whose call it is. `X-Forwarded-For` counts only if it comes from a trusted
    proxy (addresses, networks or host names), and from it the last address that
    is not one too: what is further left may be anything."""
    names = [item.strip() for item in trusted.split(",") if item.strip()]
    address = _address(peer or "")
    if address is None:
        return peer or "unknown"
    for hop in reversed([h for h in (forwarded or "").split(",") if h.strip()]):
        if not _is_trusted(address, names, resolve):
            break
        previous = _address(hop)
        if previous is None:
            break
        address = previous
    if address.version == 6:  # one customer has a whole /64
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def enforce_rate_limit(request: Request) -> None:
    """For the whole application: it looks at the route."""
    group = GROUPS_BY_ROUTE.get((request.method, getattr(request.scope.get("route"), "path", "")))
    if group is None:
        return
    address = client_address(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        os.environ.get("TRUSTED_PROXIES", ""),
    )
    wait = limiter.wait(group, address)
    if wait > 0:
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes. Probá de nuevo en un rato.",
            headers={"Retry-After": str(math.ceil(wait))},
        )
