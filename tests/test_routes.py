"""Flask routes, API validation, error handling and security controls."""
import time

import pytest

from app import create_app
from config import TestConfig
from dns_engine import DNSQueryEngine
from dns_engine.validation import ValidationError, normalize_domain
from tests.conftest import run

PAGES = ["/", "/dashboard", "/diagnostics", "/comparison", "/analytics", "/reports", "/history", "/about"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert b"DNSGuard" in r.data
    assert b'name="csrf-token"' in r.data


def test_resolve_success_schema(client):
    r = run(client, domain="www.example.com", attempts=5)
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    d = body["data"]
    assert d["id"] is not None
    assert d["resolver_keys"] == ["google", "cloudflare"]
    assert len(d["attempts"]["google"]) == 5 and len(d["attempts"]["cloudflare"]) == 5
    a = d["attempts"]["google"][0]
    for field in ("domain", "resolver_name", "resolver_ip", "record_type", "records", "rcode",
                  "latency_ms", "success", "timestamp", "error", "category"):
        assert field in a
    assert d["overall"]["total"] == 10
    assert d["diagnosis"]["severity"] == "ok"


def test_resolve_single_resolver(client):
    d = run(client, resolvers="cloudflare").get_json()["data"]
    assert d["resolver_keys"] == ["cloudflare"]
    assert list(d["attempts"]) == ["cloudflare"]


def test_compare_endpoint_forces_both(client):
    r = client.post("/api/dns/compare", json={"domain": "differ.example.com", "resolvers": "google", "attempts": 3})
    d = r.get_json()["data"]
    assert d["resolver_keys"] == ["google", "cloudflare"]
    assert d["comparison"]["record_consistency"]["status"] == "different"


def test_url_input_is_normalised(client):
    d = run(client, domain="https://WWW.Example.com/some/path?q=1").get_json()["data"]
    assert d["domain"] == "www.example.com"


# 10. Invalid domain input
@pytest.mark.parametrize("domain", [
    "", "   ", "localhost", "8.8.8.8", "2001:db8::1", "exa mple.com", "-bad.example.com", "bad-.example.com",
    "a..b.com", "x" * 64 + ".com", ("a." * 130) + "com", "user@example.com", "example.123", None, 42,
])
def test_invalid_domain_rejected(client, domain):
    r = client.post("/api/dns/resolve", json={"domain": domain, "attempts": 1})
    assert r.status_code == 400
    body = r.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["field"] == "domain"


def test_idn_domain_is_converted():
    assert normalize_domain("bücher.example") == "xn--bcher-kva.example"
    assert normalize_domain("Example.COM.") == "example.com"
    with pytest.raises(ValidationError):
        normalize_domain("not a domain")


@pytest.mark.parametrize("body, field", [
    ({"domain": "example.com", "record_type": "MX"}, "record_type"),
    ({"domain": "example.com", "record_type": "TXT"}, "record_type"),
    ({"domain": "example.com", "attempts": 7}, "attempts"),
    ({"domain": "example.com", "attempts": 1000}, "attempts"),
    ({"domain": "example.com", "attempts": "many"}, "attempts"),
    ({"domain": "example.com", "timeout": 0.01}, "timeout"),
    ({"domain": "example.com", "timeout": 60}, "timeout"),
    ({"domain": "example.com", "timeout": "nan"}, "timeout"),
    ({"domain": "example.com", "resolvers": "quad9"}, "resolvers"),
    ({"domain": "example.com", "resolvers": ["8.8.4.4"]}, "resolvers"),
    ({"domain": "example.com", "resolver_ip": "203.0.113.5"}, "resolvers"),
])
def test_parameter_validation(client, body, field):
    r = client.post("/api/dns/resolve", json=body)
    assert r.status_code == 400
    assert r.get_json()["error"]["field"] == field


# 13. API error handling
def test_malformed_json_returns_400(client):
    r = client.post("/api/dns/resolve", data="{not json", content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "invalid_json"
    r = client.post("/api/dns/resolve", json=["a", "list"])
    assert r.status_code == 400


def test_unknown_api_route_returns_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_unknown_page_returns_html_404(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404
    assert b"404" in r.data and b"<html" in r.data


def test_method_not_allowed_json(client):
    r = client.get("/api/dns/resolve")
    assert r.status_code == 405
    assert r.get_json()["ok"] is False


def test_internal_errors_hide_details(db_path):
    def broken_udp(*a, **k):
        raise RuntimeError("secret internal detail /etc/passwd")
    app = create_app(TestConfig, engine=DNSQueryEngine(udp=broken_udp), DATABASE=db_path)
    r = run(app.test_client())
    assert r.status_code == 500
    text = r.get_data(as_text=True)
    assert "secret" not in text and "Traceback" not in text
    assert r.get_json()["error"]["code"] == "test_failed"


def test_async_job_reports_progress_and_result(client):
    r = client.post("/api/dns/resolve", json={"domain": "example.com", "attempts": 5, "async": True})
    assert r.status_code == 202
    job_id = r.get_json()["data"]["job_id"]
    for _ in range(100):
        job = client.get(f"/api/dns/jobs/{job_id}").get_json()["data"]
        if job["state"] != "running":
            break
        time.sleep(0.05)
    assert job["state"] == "done"
    assert job["completed"] == job["total"] == 10
    assert job["progress"] == 100.0
    assert job["result"]["id"] is not None


def test_unknown_job_404(client):
    assert client.get("/api/dns/jobs/abc123").status_code == 404
    assert client.get("/api/dns/jobs/../../etc").status_code == 404


def test_csrf_required_when_enabled(engine, db_path):
    app = create_app(TestConfig, engine=engine, DATABASE=db_path, CSRF_ENABLED=True)
    c = app.test_client()
    r = c.post("/api/dns/resolve", json={"domain": "example.com", "attempts": 1})
    assert r.status_code == 403
    assert r.get_json()["error"]["code"] == "csrf_failed"
    page = c.get("/diagnostics").get_data(as_text=True)
    token = page.split('name="csrf-token" content="')[1].split('"')[0]
    r = c.post("/api/dns/resolve", json={"domain": "example.com", "attempts": 1}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200
    r = c.delete("/api/history/1", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403
    assert c.get("/api/history").status_code == 200  # reads need no token


def test_rate_limit(engine, db_path):
    app = create_app(TestConfig, engine=engine, DATABASE=db_path, RATE_LIMIT_ENABLED=True, RATE_LIMIT_PER_MINUTE=3)
    c = app.test_client()
    codes = [run(c, attempts=1, resolvers="google").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]


def test_meta_and_status(client):
    meta = client.get("/api/meta").get_json()["data"]
    assert meta["record_types"] == ["A", "AAAA"]
    assert meta["attempts"] == [1, 3, 5, 10, 20]
    assert {r["ip"] for r in meta["resolvers"].values()} == {"8.8.8.8", "1.1.1.1"}
    status = client.get("/api/status").get_json()["data"]
    assert status["app"] == "online" and status["database"] == "ok"


def test_domain_is_escaped_in_rendered_pages(client):
    # Templates autoescape; nothing user-controlled is rendered server-side unescaped.
    r = client.get("/diagnostics?domain=<script>alert(1)</script>")
    assert b"<script>alert(1)</script>" not in r.data
