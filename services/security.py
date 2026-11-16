"""
Request security helpers: CSRF tokens for state-changing API calls, a small
per-client rate limiter for DNS test endpoints, and security headers.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import current_app, jsonify, request, session

CSRF_HEADER = "X-CSRF-Token"
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_protect():
    """before_request hook: require a valid token on state-changing /api calls."""
    if not current_app.config.get("CSRF_ENABLED", True):
        return None
    if request.method not in STATE_CHANGING or not request.path.startswith("/api/"):
        return None
    sent = request.headers.get(CSRF_HEADER, "")
    expected = session.get("csrf_token", "")
    if not sent or not expected or not hmac.compare_digest(sent, expected):
        return jsonify({"ok": False, "error": {"code": "csrf_failed",
                                               "message": "Security token missing or invalid. Reload the page and try again."}}), 403
    return None


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


rate_limiter = RateLimiter()


def check_rate_limit():
    """Returns an error response when the client exceeded the DNS-test rate limit, else None."""
    if not current_app.config.get("RATE_LIMIT_ENABLED", True):
        return None
    key = request.remote_addr or "unknown"
    if not rate_limiter.allow(key, current_app.config.get("RATE_LIMIT_PER_MINUTE", 30)):
        return jsonify({"ok": False, "error": {"code": "rate_limited",
                                               "message": "Too many DNS tests in a short time. Please wait a minute."}}), 429
    return None


def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'none'",
    )
    return response
