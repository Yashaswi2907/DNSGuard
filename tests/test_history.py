"""SQLite history: storage, retrieval, filtering, deletion, export and statistics."""
import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from config import TestConfig
from tests.conftest import run


# 11. Database storage
def test_test_and_attempts_are_stored(client, db_path):
    test_id = run(client, domain="www.example.com", attempts=3).get_json()["data"]["id"]
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT domain, record_type, resolvers, attempts, total_queries, successful, failed, "
                       "failure_rate, median_latency_ms, outcome FROM tests WHERE id = ?", (test_id,)).fetchone()
    assert row[0] == "www.example.com" and row[1] == "A"
    assert json.loads(row[2]) == ["google", "cloudflare"]
    assert row[3] == 3 and row[4] == 6 and row[5] == 6 and row[6] == 0
    assert row[7] == 0.0 and row[8] is not None and row[9] == "SUCCESS"
    n = conn.execute("SELECT COUNT(*) FROM query_attempts WHERE test_id = ?", (test_id,)).fetchone()[0]
    assert n == 6
    conn.close()


def test_save_false_does_not_store(client):
    d = run(client, save=False).get_json()["data"]
    assert d["id"] is None
    assert client.get("/api/history").get_json()["data"]["total"] == 0


# 12. History retrieval
def test_history_list_and_detail(client):
    ids = [run(client, domain=d).get_json()["data"]["id"] for d in ("example.com", "nx-a.example.com", "example.org")]
    data = client.get("/api/history").get_json()["data"]
    assert data["total"] == 3
    assert [t["id"] for t in data["items"]] == ids[::-1]  # newest first

    detail = client.get(f"/api/history/{ids[1]}").get_json()["data"]
    assert detail["domain"] == "nx-a.example.com"
    assert detail["outcome"] == "NXDOMAIN"
    assert detail["failure_rate"] == 100.0
    assert detail["median_latency_ms"] is None
    assert set(detail["attempts_by_resolver"]) == {"google", "cloudflare"}
    assert detail["diagnosis"]["resolvers"]["google"]["status"] == "NXDOMAIN"
    assert detail["comparison"]["resolvers"]["google"]["summary"]["failed"] == 3

    assert client.get("/api/history/9999").status_code == 404
    assert client.get("/api/history/latest").get_json()["data"]["id"] == ids[2]


def test_search_and_filters(client):
    run(client, domain="www.example.com")
    run(client, domain="example.org", record_type="AAAA")
    run(client, domain="nx-x.example.net")
    q = lambda s: client.get("/api/history" + s).get_json()["data"]  # noqa: E731
    assert q("?q=example.org")["total"] == 1
    assert q("?q=EXAMPLE")["total"] == 3
    assert q("?q=%25")["total"] == 0          # LIKE wildcard is escaped, not interpreted
    assert q("?record_type=AAAA")["total"] == 1
    assert q("?outcome=NXDOMAIN")["total"] == 1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    assert q(f"?from={today}&to={today}")["total"] == 3
    assert q(f"?from={tomorrow}")["total"] == 0
    assert client.get("/api/history?from=not-a-date").status_code == 400


def test_sorting_is_whitelisted(client):
    run(client, domain="b.example.com")
    run(client, domain="a.example.com")
    items = client.get("/api/history?sort=domain&order=asc").get_json()["data"]["items"]
    assert [t["domain"] for t in items] == ["a.example.com", "b.example.com"]
    # SQL injection attempt in sort/order falls back to the default column safely
    r = client.get("/api/history?sort=domain;DROP TABLE tests&order=x")
    assert r.status_code == 200
    assert client.get("/api/history").get_json()["data"]["total"] == 2


def test_pagination(client):
    for i in range(5):
        run(client, domain=f"p{i}.example.com", attempts=1)
    page = client.get("/api/history?limit=2&offset=2").get_json()["data"]
    assert page["total"] == 5 and len(page["items"]) == 2


def test_delete_single(client, db_path):
    a = run(client).get_json()["data"]["id"]
    b = run(client).get_json()["data"]["id"]
    r = client.delete(f"/api/history/{a}")
    assert r.status_code == 200 and r.get_json()["data"]["deleted"] == a
    assert client.delete(f"/api/history/{a}").status_code == 404
    assert [t["id"] for t in client.get("/api/history").get_json()["data"]["items"]] == [b]
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM query_attempts WHERE test_id = ?", (a,)).fetchone()[0] == 0  # cascade
    conn.close()


def test_clear_requires_confirmation(client):
    run(client)
    run(client)
    r = client.delete("/api/history")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "confirmation_required"
    assert client.get("/api/history").get_json()["data"]["total"] == 2
    r = client.delete("/api/history", json={"confirm": True})
    assert r.get_json()["data"]["deleted"] == 2
    assert client.get("/api/history").get_json()["data"]["total"] == 0


def test_history_persists_across_restart(engine, db_path):
    app1 = create_app(TestConfig, engine=engine, DATABASE=db_path)
    test_id = run(app1.test_client(), domain="persist.example.com").get_json()["data"]["id"]
    app2 = create_app(TestConfig, engine=engine, DATABASE=db_path)  # a fresh application instance
    detail = app2.test_client().get(f"/api/history/{test_id}").get_json()["data"]
    assert detail["domain"] == "persist.example.com"


def test_export_csv(client):
    test_id = run(client, domain="www.example.com", attempts=3).get_json()["data"]["id"]
    r = client.get("/api/history/export/csv")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(r.get_data(as_text=True))))
    assert len(rows) == 6
    assert rows[0]["test_id"] == str(test_id)
    assert rows[0]["records"] == "192.0.2.10 192.0.2.11"
    assert rows[0]["cname_chain"] == "www.example.com -> edge.cdn.example.net"
    single = client.get(f"/api/history/export/csv?test_id={test_id}")
    assert single.status_code == 200 and f"dnsguard-test-{test_id}.csv" in single.headers["Content-Disposition"]
    assert client.get("/api/history/export/csv?test_id=999").status_code == 404


def test_export_json(client):
    test_id = run(client).get_json()["data"]["id"]
    data = json.loads(client.get("/api/history/export/json").get_data(as_text=True))
    assert len(data["tests"]) == 1 and len(data["attempts"]) == 6
    one = json.loads(client.get(f"/api/history/export/json?test_id={test_id}").get_data(as_text=True))
    assert one["test"]["id"] == test_id


def test_csv_formula_injection_neutralised():
    from database.history import _safe_csv
    assert _safe_csv("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert _safe_csv("+1") == "'+1"
    assert _safe_csv("example.com") == "example.com"
    assert _safe_csv(12) == 12


def test_dashboard_stats_are_computed_from_stored_data(client):
    empty = client.get("/api/dashboard/stats").get_json()["data"]
    assert empty["total_queries"] == 0 and empty["failure_rate"] is None and empty["median_latency_ms"] is None
    assert empty["resolver_health"]["google"]["status"] == "unknown"

    run(client, domain="example.com", attempts=5)            # 10 successes
    run(client, domain="timeout.example.com", attempts=5)    # 10 timeouts
    run(client, domain="ipv4only.example.com", record_type="AAAA", attempts=5)  # 10 no-data
    s = client.get("/api/dashboard/stats").get_json()["data"]
    assert s["tests"] == 3
    assert s["total_queries"] == 30
    assert s["successful"] == 10 and s["no_data"] == 10 and s["failed"] == 10
    assert s["failure_rate"] == pytest.approx(33.33, abs=0.01)
    assert s["median_latency_ms"] is not None
    h = s["resolver_health"]["google"]
    assert h["observations"] == 15 and h["resolver_failures"] == 5
    assert h["status"] == "unresponsive"  # 66.7% answered < 70%
    assert sum(d["successful"] + d["no_data"] + d["failed"] for d in s["activity"]) == 30
    assert len(s["recent_tests"]) == 3


def test_analytics_aggregates(client):
    run(client, domain="example.com", attempts=3)
    run(client, domain="example.com", record_type="AAAA", attempts=3)
    a = client.get("/api/analytics").get_json()["data"]
    assert a["by_record_type"]["A"]["google"]["successful"] == 3
    assert a["by_record_type"]["AAAA"]["cloudflare"]["total"] == 3
    assert sum(a["distribution"]["series"]["google"]) == 6
    assert a["categories"] == {"SUCCESS": 12}
    assert len(a["trend"]) == 2
