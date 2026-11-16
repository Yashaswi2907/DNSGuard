"""
Resolver configuration.

DNSGuard talks to exactly two recursive resolvers, both taken from the
allow-list in ``config.RESOLVERS``. A client can only *name* a resolver by
its key ("google" / "cloudflare"); it can never supply an IP address.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from config import RESOLVERS


class UnknownResolverError(ValueError):
    """Raised when a resolver key is not on the allow-list."""


@dataclass(frozen=True)
class ResolverEndpoint:
    key: str
    name: str
    short: str
    ip: str
    ipv6: str
    operator: str
    docs: str
    port: int = 53

    def to_dict(self) -> dict:
        return asdict(self)


def get_resolver(key: str) -> ResolverEndpoint:
    """Return the configured resolver for ``key`` or raise UnknownResolverError."""
    if not isinstance(key, str) or key not in RESOLVERS:
        raise UnknownResolverError(f"Unknown resolver: {key!r}")
    return ResolverEndpoint(**RESOLVERS[key])


def list_resolvers() -> list[ResolverEndpoint]:
    return [ResolverEndpoint(**cfg) for cfg in RESOLVERS.values()]


def resolve_selection(selection: str | list[str]) -> list[ResolverEndpoint]:
    """
    Turn a UI selection ("google", "cloudflare", "both" or a list of keys)
    into resolver endpoints. Order is stable: Google first, then Cloudflare.
    """
    if isinstance(selection, str):
        keys = list(RESOLVERS.keys()) if selection == "both" else [selection]
    elif isinstance(selection, (list, tuple)):
        keys = list(selection)
    else:
        raise UnknownResolverError("Resolver selection must be a string or list")

    if not keys:
        raise UnknownResolverError("At least one resolver must be selected")

    endpoints = [get_resolver(k) for k in keys]
    seen: set[str] = set()
    unique = []
    for ep in endpoints:
        if ep.key not in seen:
            seen.add(ep.key)
            unique.append(ep)
    order = list(RESOLVERS.keys())
    return sorted(unique, key=lambda e: order.index(e.key))
