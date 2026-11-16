"""Test history API routes (list, detail, delete, clear, export)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import Blueprint, Response, request

from database import get_db
from database import history as h

from .api_utils import error, ok

history_bp = Blueprint("history_api", __name__, url_prefix="/api/history")


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


@history_bp.get("")
def list_history():
    search = (request.args.get("q") or "").strip()[:253] or None
    try:
        data = h.list_tests(
            get_db(),
            search=search,
            date_from=request.args.get("from"),
            date_to=request.args.get("to"),
            record_type=(request.args.get("record_type") or "").upper() or None,
            outcome=(request.args.get("outcome") or "").upper() or None,
            limit=_int_arg("limit", 50, 1, 500),
            offset=_int_arg("offset", 0, 0, 10**9),
            sort=request.args.get("sort", "created_at"),
            order=request.args.get("order", "desc"),
        )
    except ValueError as exc:
        return error("validation_error", str(exc), 400, "date")
    return ok(data)


@history_bp.get("/latest")
def latest():
    test_id = h.latest_test_id(get_db())
    if test_id is None:
        return ok(None)
    return ok(h.get_test(get_db(), test_id))


@history_bp.get("/<int:test_id>")
def get_one(test_id: int):
    test = h.get_test(get_db(), test_id)
    if test is None:
        return error("not_found", f"Test #{test_id} was not found.", 404)
    return ok(test)


@history_bp.delete("/<int:test_id>")
def delete_one(test_id: int):
    if not h.delete_test(get_db(), test_id):
        return error("not_found", f"Test #{test_id} was not found.", 404)
    return ok({"deleted": test_id})


@history_bp.delete("")
def clear():
    payload = request.get_json(silent=True) or {}
    if payload.get("confirm") is not True:
        return error("confirmation_required", "Send {\"confirm\": true} to clear the entire history.", 400)
    removed = h.clear_history(get_db())
    return ok({"deleted": removed})


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


@history_bp.get("/export/csv")
def export_csv_all():
    test_id = request.args.get("test_id", type=int)
    if test_id is not None and h.get_test(get_db(), test_id) is None:
        return error("not_found", f"Test #{test_id} was not found.", 404)
    body = h.export_csv(get_db(), test_id)
    name = f"dnsguard-test-{test_id}.csv" if test_id else f"dnsguard-history-{_stamp()}.csv"
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@history_bp.get("/export/json")
def export_json_all():
    test_id = request.args.get("test_id", type=int)
    if test_id is not None and h.get_test(get_db(), test_id) is None:
        return error("not_found", f"Test #{test_id} was not found.", 404)
    body = json.dumps(h.export_json(get_db(), test_id), indent=2)
    name = f"dnsguard-test-{test_id}.json" if test_id else f"dnsguard-history-{_stamp()}.json"
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
