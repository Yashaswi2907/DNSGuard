"""
DNSGuard configuration.

All tunable limits live here so that the security boundaries of the
application (which resolvers may be queried, how many attempts, how long a
timeout may be) are defined in exactly one place.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines) so python-dotenv is not required."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# DNS resolvers. This is an allow-list: the API only accepts these keys and
# never accepts a raw IP address from the client (prevents use as an open
# DNS proxy / scanner).
# ---------------------------------------------------------------------------
RESOLVERS: dict[str, dict[str, str]] = {
    "google": {
        "key": "google",
        "name": "Google Public DNS",
        "short": "Google",
        "ip": "8.8.8.8",
        "ipv6": "2001:4860:4860::8888",
        "operator": "Google LLC",
        "docs": "https://developers.google.com/speed/public-dns",
    },
    "cloudflare": {
        "key": "cloudflare",
        "name": "Cloudflare DNS",
        "short": "Cloudflare",
        "ip": "1.1.1.1",
        "ipv6": "2606:4700:4700::1111",
        "operator": "Cloudflare, Inc.",
        "docs": "https://developers.cloudflare.com/1.1.1.1/",
    },
}

RECORD_TYPES: tuple[str, ...] = ("A", "AAAA")
ALLOWED_ATTEMPTS: tuple[int, ...] = (1, 3, 5, 10, 20)

TIMEOUT_MIN_S = 0.5
TIMEOUT_MAX_S = 10.0
TIMEOUT_DEFAULT_S = 2.0

# Hard ceiling on total network queries one request may trigger
# (attempts x resolvers). 20 attempts x 2 resolvers = 40.
MAX_QUERIES_PER_TEST = 40


class Config:
    SECRET_KEY = os.environ.get("DNSGUARD_SECRET_KEY") or os.urandom(32).hex()
    DATABASE = os.environ.get("DNSGUARD_DATABASE") or str(INSTANCE_DIR / "dnsguard.db")
    CSRF_ENABLED = True
    # Simple in-memory rate limit for DNS test endpoints (per client IP).
    RATE_LIMIT_ENABLED = os.environ.get("DNSGUARD_RATE_LIMIT", "1") != "0"
    RATE_LIMIT_PER_MINUTE = int(os.environ.get("DNSGUARD_RATE_LIMIT_PER_MINUTE", "30"))
    JSON_SORT_KEYS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    TESTING = False


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    CSRF_ENABLED = False
    RATE_LIMIT_ENABLED = False
