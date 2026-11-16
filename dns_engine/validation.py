"""
Input validation for DNS test requests.

Everything that reaches the DNS engine passes through ``validate_test_request``
so the engine never sees an arbitrary resolver IP, an unsupported record type,
an unbounded number of attempts, or a malformed name.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from config import (
    ALLOWED_ATTEMPTS,
    MAX_QUERIES_PER_TEST,
    RECORD_TYPES,
    TIMEOUT_DEFAULT_S,
    TIMEOUT_MAX_S,
    TIMEOUT_MIN_S,
)
from .resolver import ResolverEndpoint, UnknownResolverError, resolve_selection

LABEL_RE = re.compile(r"^(?!-)[a-z0-9_-]{1,63}(?<!-)$")


class ValidationError(ValueError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass
class DNSTestRequest:
    domain: str
    record_type: str
    resolvers: list[ResolverEndpoint]
    attempts: int
    timeout: float

    @property
    def resolver_keys(self) -> list[str]:
        return [r.key for r in self.resolvers]


def normalize_domain(raw) -> str:
    """Return a lower-case ASCII (IDNA) domain without trailing dot, or raise."""
    if not isinstance(raw, str):
        raise ValidationError("Domain name is required.", "domain")
    value = raw.strip()
    if not value:
        raise ValidationError("Domain name is required.", "domain")
    if len(value) > 300:
        raise ValidationError("Domain name is too long.", "domain")

    # Be forgiving if a full URL is pasted: keep only the host part.
    if "://" in value:
        host = urlsplit(value).hostname
        if not host:
            raise ValidationError("Could not find a domain name in that URL.", "domain")
        value = host
    elif "/" in value:
        value = value.split("/", 1)[0]

    value = value.rstrip(".").lower()
    if " " in value or "@" in value or ":" in value:
        raise ValidationError("Enter a domain name only, for example example.com.", "domain")

    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValidationError(
            "That is an IP address. DNSGuard performs forward lookups (name → address); enter a domain name.",
            "domain",
        )

    try:
        ascii_value = value.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValidationError("Domain name contains characters that cannot be encoded (IDNA).", "domain")

    if len(ascii_value) > 253:
        raise ValidationError("Domain name exceeds 253 characters.", "domain")
    labels = ascii_value.split(".")
    if len(labels) < 2:
        raise ValidationError("Enter a fully qualified domain name, for example example.com.", "domain")
    for label in labels:
        if not LABEL_RE.match(label):
            raise ValidationError(
                f"Invalid label '{label or '(empty)'}': labels are 1–63 letters, digits or hyphens "
                "and cannot start or end with a hyphen.",
                "domain",
            )
    if labels[-1].isdigit():
        raise ValidationError("The top-level domain cannot be numeric.", "domain")
    return ascii_value


def validate_record_type(raw) -> str:
    value = str(raw or "A").strip().upper()
    if value not in RECORD_TYPES:
        raise ValidationError(f"Record type must be one of: {', '.join(RECORD_TYPES)}.", "record_type")
    return value


def validate_attempts(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError("Number of attempts must be a whole number.", "attempts")
    if value not in ALLOWED_ATTEMPTS:
        raise ValidationError(
            f"Number of attempts must be one of: {', '.join(map(str, ALLOWED_ATTEMPTS))}.", "attempts"
        )
    return value


def validate_timeout(raw) -> float:
    if raw is None or raw == "":
        return TIMEOUT_DEFAULT_S
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValidationError("Timeout must be a number of seconds.", "timeout")
    if value != value or not (TIMEOUT_MIN_S <= value <= TIMEOUT_MAX_S):  # NaN check
        raise ValidationError(
            f"Timeout must be between {TIMEOUT_MIN_S:g} and {TIMEOUT_MAX_S:g} seconds.", "timeout"
        )
    return round(value, 2)


def validate_resolvers(raw) -> list[ResolverEndpoint]:
    if raw is None or raw == "":
        raw = "both"
    try:
        return resolve_selection(raw)
    except UnknownResolverError:
        raise ValidationError("Resolver must be 'google', 'cloudflare' or 'both'.", "resolvers")


def validate_test_request(payload: dict | None, force_both: bool = False) -> DNSTestRequest:
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    if "resolver_ip" in payload or "nameserver" in payload or "server" in payload:
        raise ValidationError("Custom resolver addresses are not accepted; choose google, cloudflare or both.",
                              "resolvers")
    domain = normalize_domain(payload.get("domain"))
    record_type = validate_record_type(payload.get("record_type", "A"))
    resolvers = validate_resolvers("both" if force_both else payload.get("resolvers", payload.get("resolver")))
    attempts = validate_attempts(payload.get("attempts", 3))
    timeout = validate_timeout(payload.get("timeout"))
    if attempts * len(resolvers) > MAX_QUERIES_PER_TEST:
        raise ValidationError("Too many queries requested for a single test.", "attempts")
    return DNSTestRequest(domain, record_type, resolvers, attempts, timeout)
