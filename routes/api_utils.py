"""Consistent JSON response helpers for the API."""
from __future__ import annotations

from flask import current_app, jsonify


def ok(data=None, status: int = 200, **extra):
    body = {"ok": True, "data": data}
    body.update(extra)
    return jsonify(body), status


def error(code: str, message: str, status: int = 400, field: str | None = None):
    payload = {"code": code, "message": message}
    if field:
        payload["field"] = field
    return jsonify({"ok": False, "error": payload}), status


def engine():
    return current_app.extensions["dnsguard.engine"]


def jobs():
    return current_app.extensions["dnsguard.jobs"]


def resolver_meta() -> dict:
    from dns_engine import list_resolvers
    return {r.key: r.to_dict() for r in list_resolvers()}
