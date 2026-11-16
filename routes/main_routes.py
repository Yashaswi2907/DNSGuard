"""HTML page routes."""
from __future__ import annotations

from flask import Blueprint, render_template


main_bp = Blueprint("main", __name__)


def _page(template: str, page: str, title: str, **ctx):
    # Resolver list, limits and the CSRF token are injected by app.context_processor.
    return render_template(template, page=page, title=title, **ctx)


@main_bp.get("/")
def index():
    return _page("index.html", "home", "DNSGuard — DNS Diagnostics & Resolver Reliability")


@main_bp.get("/dashboard")
def dashboard():
    return _page("dashboard.html", "dashboard", "Overview")


@main_bp.get("/diagnostics")
def diagnostics():
    return _page("diagnostics.html", "diagnostics", "DNS Diagnostics")


@main_bp.get("/comparison")
def comparison():
    return _page("comparison.html", "comparison", "Resolver Comparison")


@main_bp.get("/analytics")
def analytics():
    return _page("analytics.html", "analytics", "Performance Analytics")


@main_bp.get("/reports")
def reports():
    return _page("reports.html", "reports", "Diagnostic Reports")


@main_bp.get("/history")
def history():
    return _page("history.html", "history", "Test History")


@main_bp.get("/about")
def about():
    return _page("about.html", "about", "About DNS")
