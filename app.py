"""
DNSGuard – DNS Diagnostics and Resolver Reliability Analysis System
Flask application factory and entry point.

Run:  python app.py            (http://127.0.0.1:5000)
"""
from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from config import (ALLOWED_ATTEMPTS, RECORD_TYPES, TIMEOUT_DEFAULT_S, TIMEOUT_MAX_S, TIMEOUT_MIN_S,
                    Config)
from database import init_app as init_db_app
from dns_engine import DNSQueryEngine, list_resolvers
from routes import dns_bp, history_bp, main_bp
from services.jobs import JobManager
from services.security import apply_security_headers, csrf_protect, get_csrf_token


def create_app(config_object=Config, engine: DNSQueryEngine | None = None, **overrides) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    app.config.update(overrides)
    app.json.sort_keys = False  # keep resolver order (Google, then Cloudflare)

    init_db_app(app)
    app.extensions["dnsguard.engine"] = engine or DNSQueryEngine()
    app.extensions["dnsguard.jobs"] = JobManager()

    app.register_blueprint(main_bp)
    app.register_blueprint(dns_bp)
    app.register_blueprint(history_bp)

    app.before_request(csrf_protect)
    app.after_request(apply_security_headers)

    @app.context_processor
    def inject_globals():
        return {
            "csrf_token": get_csrf_token,
            "app_version": "1.0.0",
            "resolvers": [r.to_dict() for r in list_resolvers()],
            "record_types": RECORD_TYPES,
            "allowed_attempts": ALLOWED_ATTEMPTS,
            "timeout_default": TIMEOUT_DEFAULT_S,
            "timeout_min": TIMEOUT_MIN_S,
            "timeout_max": TIMEOUT_MAX_S,
        }

    def _error_page(code: int, name: str):
        try:
            return render_template("error.html", code=code, name=name, page="error", title=f"{code} {name}"), code
        except Exception:  # template failure must not mask the original error
            return f"{code} {name}", code, {"Content-Type": "text/plain; charset=utf-8"}

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"code": exc.name.lower().replace(" ", "_"),
                                                   "message": exc.description}}), exc.code
        return _error_page(exc.code, exc.name)

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):  # never expose stack traces to users
        app.logger.exception("Unhandled error")
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": {"code": "internal_error",
                                                   "message": "An unexpected error occurred."}}), 500
        return _error_page(500, "Internal Server Error")

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    application = create_app()
    application.run(
        host=os.environ.get("DNSGUARD_HOST", "127.0.0.1"),
        port=int(os.environ.get("DNSGUARD_PORT", "5000")),
        debug=os.environ.get("DNSGUARD_DEBUG", "0") == "1",
        threaded=True,
    )
