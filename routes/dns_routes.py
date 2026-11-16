"""DNS test, dashboard and analytics API routes."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, request

from config import (ALLOWED_ATTEMPTS, MAX_QUERIES_PER_TEST, RECORD_TYPES, TIMEOUT_DEFAULT_S, TIMEOUT_MAX_S,
                    TIMEOUT_MIN_S)
from database import get_db
from database.history import analytics as analytics_data
from database.history import dashboard_stats, save_test
from diagnostics import RULES
from dns_engine import ValidationError, validate_test_request
from services.jobs import TooManyJobsError
from services.runner import run_dns_test
from services.security import check_rate_limit

from .api_utils import engine, error, jobs, ok, resolver_meta

dns_bp = Blueprint("dns_api", __name__, url_prefix="/api")


def _start_test(force_both: bool):
    payload = request.get_json(silent=True)
    if payload is None:
        return error("invalid_json", "Request body must be valid JSON.", 400)
    try:
        req = validate_test_request(payload, force_both=force_both)
    except ValidationError as exc:
        return error("validation_error", exc.message, 400, exc.field)

    limited = check_rate_limit()
    if limited:
        return limited

    save = payload.get("save", True) is not False
    if payload.get("async"):
        try:
            job_id = jobs().start(req, engine(), current_app.config["DATABASE"], save=save)
        except TooManyJobsError as exc:
            return error("busy", str(exc), 429)
        return ok({"job_id": job_id, "total": req.attempts * len(req.resolvers)}, 202)

    try:
        result = run_dns_test(req, engine())
    except Exception:
        current_app.logger.exception("DNS test failed")
        return error("test_failed", "The DNS test could not be completed.", 500)
    if save:
        result["id"] = save_test(get_db(), result)
    return ok(result)


@dns_bp.post("/dns/resolve")
def resolve():
    """Run a DNS test against the selected resolver(s)."""
    return _start_test(force_both=False)


@dns_bp.post("/dns/compare")
def compare():
    """Run the same test against both resolvers and return the comparison."""
    return _start_test(force_both=True)


@dns_bp.get("/dns/jobs/<job_id>")
def job_status(job_id: str):
    if not job_id.isalnum() or len(job_id) > 64:
        return error("not_found", "Job not found.", 404)
    job = jobs().get(job_id)
    if job is None:
        return error("not_found", "Job not found or expired.", 404)
    return ok(job)


@dns_bp.get("/meta")
def meta():
    return ok({
        "resolvers": resolver_meta(),
        "record_types": list(RECORD_TYPES),
        "attempts": list(ALLOWED_ATTEMPTS),
        "timeout": {"min": TIMEOUT_MIN_S, "max": TIMEOUT_MAX_S, "default": TIMEOUT_DEFAULT_S},
        "max_queries_per_test": MAX_QUERIES_PER_TEST,
    })


@dns_bp.get("/status")
def status():
    try:
        get_db().execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    return ok({"app": "online", "database": "ok" if db_ok else "error",
               "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds")})


@dns_bp.get("/dashboard/stats")
def stats():
    return ok(dashboard_stats(get_db(), resolver_meta()))


@dns_bp.get("/analytics")
def analytics():
    return ok(analytics_data(get_db(), resolver_meta()))


@dns_bp.get("/diagnostics/rules")
def rules():
    return ok({k: {kk: vv for kk, vv in v.items()} for k, v in RULES.items()})
