"""
Test history persistence and aggregate statistics.

All SQL uses ``?`` placeholders (parameterised queries); user input is never
interpolated into SQL text.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from dns_engine import response_classifier as rc
from dns_engine.performance import median

# Categories that indicate the *resolver* did not deliver an answer
# (as opposed to NXDOMAIN / NODATA, which are valid answers about the name).
RESOLVER_FAILURE_CATEGORIES = (rc.TIMEOUT, rc.NETWORK_ERROR, rc.SERVFAIL, rc.REFUSED, rc.OTHER_ERROR)


# ---------------------------------------------------------------- write path
def save_test(conn: sqlite3.Connection, result: dict) -> int:
    overall = result["overall"]
    cur = conn.execute(
        """
        INSERT INTO tests (domain, record_type, resolvers, attempts, timeout_s, created_at, duration_ms,
                           total_queries, successful, no_data, failed, median_latency_ms, failure_rate,
                           outcome, report_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result["domain"], result["record_type"], json.dumps(result["resolver_keys"]),
            result["attempts_per_resolver"], result["timeout"], result["started_at"], result["duration_ms"],
            overall["total"], overall["successful"], overall["no_data"], overall["failed"],
            overall["median_latency_ms"], overall["failure_rate"], result["outcome"],
            json.dumps({"comparison": result["comparison"], "diagnosis": result["diagnosis"],
                        "resolver_meta": result["resolver_meta"]}),
        ),
    )
    test_id = cur.lastrowid
    rows = []
    for key, attempts in result["attempts"].items():
        for a in attempts:
            rows.append((
                test_id, a["resolver_key"], a["resolver_name"], a["resolver_ip"], a["attempt"], a["domain"],
                a["record_type"], a["category"], a["rcode"], int(bool(a["success"])), a["latency_ms"],
                json.dumps(a["records"]), json.dumps(a["cname_chain"]), a["ttl"], a["transport"],
                int(bool(a["tcp_fallback"])), " ".join(a.get("flags") or []), a["timestamp"], a["error"],
            ))
    conn.executemany(
        """
        INSERT INTO query_attempts (test_id, resolver_key, resolver_name, resolver_ip, attempt_no, domain,
                                    record_type, category, rcode, success, latency_ms, records, cname_chain,
                                    ttl, transport, tcp_fallback, flags, timestamp, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return test_id


def delete_test(conn: sqlite3.Connection, test_id: int) -> bool:
    cur = conn.execute("DELETE FROM tests WHERE id = ?", (test_id,))
    conn.commit()
    return cur.rowcount > 0


def clear_history(conn: sqlite3.Connection) -> int:
    count = conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0]
    conn.execute("DELETE FROM query_attempts")
    conn.execute("DELETE FROM tests")
    conn.commit()
    return count


# ----------------------------------------------------------------- read path
def _test_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "domain": row["domain"],
        "record_type": row["record_type"],
        "resolvers": json.loads(row["resolvers"]),
        "attempts": row["attempts"],
        "timeout": row["timeout_s"],
        "created_at": row["created_at"],
        "duration_ms": row["duration_ms"],
        "total_queries": row["total_queries"],
        "successful": row["successful"],
        "no_data": row["no_data"],
        "failed": row["failed"],
        "median_latency_ms": row["median_latency_ms"],
        "failure_rate": row["failure_rate"],
        "outcome": row["outcome"],
    }


def _attempt_row(row: sqlite3.Row) -> dict:
    return {
        "attempt": row["attempt_no"],
        "domain": row["domain"],
        "resolver_key": row["resolver_key"],
        "resolver_name": row["resolver_name"],
        "resolver_ip": row["resolver_ip"],
        "record_type": row["record_type"],
        "category": row["category"],
        "category_label": rc.CATEGORY_LABELS.get(row["category"], row["category"]),
        "outcome": rc.outcome_of(row["category"]),
        "rcode": row["rcode"],
        "success": bool(row["success"]),
        "latency_ms": row["latency_ms"],
        "records": json.loads(row["records"]),
        "cname_chain": json.loads(row["cname_chain"]),
        "ttl": row["ttl"],
        "transport": row["transport"],
        "tcp_fallback": bool(row["tcp_fallback"]),
        "flags": (row["flags"] or "").split(),
        "timestamp": row["timestamp"],
        "error": row["error"],
    }


def _parse_bound(value: str | None, end: bool) -> str | None:
    """Accept YYYY-MM-DD (interpreted as a UTC day) or a full ISO timestamp."""
    if not value:
        return None
    value = value.strip()
    try:
        if len(value) == 10:
            day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if end:
                day = day + timedelta(days=1)
            return day.isoformat(timespec="milliseconds")
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except ValueError:
        raise ValueError(f"Invalid date: {value!r}. Use YYYY-MM-DD.")


def list_tests(conn, search: str | None = None, date_from: str | None = None, date_to: str | None = None,
               record_type: str | None = None, outcome: str | None = None, limit: int = 50, offset: int = 0,
               sort: str = "created_at", order: str = "desc") -> dict:
    where, params = [], []
    if search:
        where.append("domain LIKE ? ESCAPE '\\'")
        escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{escaped}%")
    lo, hi = _parse_bound(date_from, False), _parse_bound(date_to, True)
    if lo:
        where.append("created_at >= ?")
        params.append(lo)
    if hi:
        where.append("created_at < ?")
        params.append(hi)
    if record_type in ("A", "AAAA"):
        where.append("record_type = ?")
        params.append(record_type)
    if outcome:
        where.append("outcome = ?")
        params.append(outcome)

    # Column names come from a fixed allow-list, never from raw input.
    sort_col = {"created_at": "created_at", "domain": "domain", "median": "median_latency_ms",
                "failure_rate": "failure_rate", "record_type": "record_type", "id": "id"}.get(sort, "created_at")
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = conn.execute(f"SELECT COUNT(*) FROM tests {clause}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM tests {clause} ORDER BY {sort_col} {direction}, id DESC LIMIT ? OFFSET ?",
        params + [int(limit), int(offset)],
    ).fetchall()
    return {"total": total, "items": [_test_row(r) for r in rows], "limit": limit, "offset": offset}


def get_test(conn, test_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
    if row is None:
        return None
    data = _test_row(row)
    report = json.loads(row["report_json"])
    attempts: dict[str, list] = {}
    for a in conn.execute(
        "SELECT * FROM query_attempts WHERE test_id = ? ORDER BY resolver_key, attempt_no", (test_id,)
    ):
        attempts.setdefault(a["resolver_key"], []).append(_attempt_row(a))
    # Keep resolver order as stored in the test (Google first, then Cloudflare).
    ordered = {k: attempts.get(k, []) for k in data["resolvers"]}
    data.update({
        "comparison": report.get("comparison"),
        "diagnosis": report.get("diagnosis"),
        "resolver_meta": report.get("resolver_meta"),
        "attempts_by_resolver": ordered,
    })
    return data


def latest_test_id(conn) -> int | None:
    row = conn.execute("SELECT id FROM tests ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
    return row[0] if row else None


# ------------------------------------------------------------------- exports
EXPORT_COLUMNS = [
    "test_id", "test_created_at", "domain", "record_type", "resolver_key", "resolver_name", "resolver_ip",
    "attempt", "category", "rcode", "success", "latency_ms", "records", "cname_chain", "ttl", "transport",
    "tcp_fallback", "timestamp", "error",
]


def _safe_csv(value):
    """Neutralise spreadsheet formula injection in exported text cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_rows(conn, test_id: int | None = None) -> list[dict]:
    sql = """
        SELECT q.*, t.created_at AS test_created_at FROM query_attempts q
        JOIN tests t ON t.id = q.test_id
    """
    params: list = []
    if test_id is not None:
        sql += " WHERE q.test_id = ?"
        params.append(test_id)
    sql += " ORDER BY q.test_id, q.resolver_key, q.attempt_no"
    out = []
    for r in conn.execute(sql, params):
        out.append({
            "test_id": r["test_id"], "test_created_at": r["test_created_at"], "domain": r["domain"],
            "record_type": r["record_type"], "resolver_key": r["resolver_key"],
            "resolver_name": r["resolver_name"], "resolver_ip": r["resolver_ip"], "attempt": r["attempt_no"],
            "category": r["category"], "rcode": r["rcode"], "success": bool(r["success"]),
            "latency_ms": r["latency_ms"], "records": json.loads(r["records"]),
            "cname_chain": json.loads(r["cname_chain"]), "ttl": r["ttl"], "transport": r["transport"],
            "tcp_fallback": bool(r["tcp_fallback"]), "timestamp": r["timestamp"], "error": r["error"],
        })
    return out


def export_csv(conn, test_id: int | None = None) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in export_rows(conn, test_id):
        row = dict(row)
        row["records"] = " ".join(row["records"])
        row["cname_chain"] = " -> ".join(
            [row["cname_chain"][0]["name"]] + [h["target"] for h in row["cname_chain"]]
        ) if row["cname_chain"] else ""
        writer.writerow({k: _safe_csv(v) for k, v in row.items()})
    return buf.getvalue()


def export_json(conn, test_id: int | None = None) -> dict:
    if test_id is not None:
        return {"test": get_test(conn, test_id)}
    tests = [_test_row(r) for r in conn.execute("SELECT * FROM tests ORDER BY created_at")]
    return {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tests": tests, "attempts": export_rows(conn)}


# ---------------------------------------------------------------- aggregates
def _latencies(conn, where: str = "", params: tuple = ()) -> list[float]:
    sql = f"SELECT latency_ms FROM query_attempts WHERE category = 'SUCCESS' AND latency_ms IS NOT NULL {where}"
    return [r[0] for r in conn.execute(sql, params)]


def dashboard_stats(conn, resolver_meta: dict, health_window: int = 50) -> dict:
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN category = 'SUCCESS' THEN 1 ELSE 0 END) AS successful,
               SUM(CASE WHEN category = 'NOERROR_NODATA' THEN 1 ELSE 0 END) AS no_data,
               MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts
        FROM query_attempts
        """
    ).fetchone()
    total = row["total"] or 0
    successful = row["successful"] or 0
    no_data = row["no_data"] or 0
    failed = total - successful - no_data
    tests_count = conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0]
    lat = _latencies(conn)

    # Resolver health from each resolver's most recent attempts.
    health = {}
    for key, meta in resolver_meta.items():
        recent = conn.execute(
            "SELECT category, latency_ms, timestamp FROM query_attempts WHERE resolver_key = ? "
            "ORDER BY timestamp DESC, id DESC LIMIT ?",
            (key, health_window),
        ).fetchall()
        n = len(recent)
        if n == 0:
            health[key] = {**meta, "status": "unknown", "label": "No observations yet", "status_short": "No data",
                           "observations": 0}
            continue
        unanswered = sum(1 for r in recent if r["category"] in RESOLVER_FAILURE_CATEGORIES)
        answered_pct = (n - unanswered) / n * 100
        succ_lat = [r["latency_ms"] for r in recent if r["category"] == rc.SUCCESS and r["latency_ms"] is not None]
        if answered_pct >= 95:
            status, label, short = "operational", "Responding normally", "Responding"
        elif answered_pct >= 70:
            status, label, short = "degraded", "Some queries unanswered", "Degraded"
        else:
            status, label, short = "unresponsive", "Most queries unanswered", "Unresponsive"
        health[key] = {
            **meta, "status": status, "label": label, "status_short": short, "observations": n,
            "answered_pct": round(answered_pct, 1),
            "resolver_failures": unanswered,
            "median_latency_ms": None if not succ_lat else round(median(succ_lat), 3),
            "last_seen": recent[0]["timestamp"],
        }

    # Daily activity for the last 14 days (UTC days).
    since = (datetime.now(timezone.utc) - timedelta(days=13)).strftime("%Y-%m-%d")
    activity_rows = conn.execute(
        """
        SELECT substr(timestamp, 1, 10) AS day,
               SUM(CASE WHEN category = 'SUCCESS' THEN 1 ELSE 0 END) AS successful,
               SUM(CASE WHEN category = 'NOERROR_NODATA' THEN 1 ELSE 0 END) AS no_data,
               SUM(CASE WHEN category NOT IN ('SUCCESS', 'NOERROR_NODATA') THEN 1 ELSE 0 END) AS failed
        FROM query_attempts WHERE substr(timestamp, 1, 10) >= ?
        GROUP BY day ORDER BY day
        """,
        (since,),
    ).fetchall()
    by_day = {r["day"]: r for r in activity_rows}
    activity = []
    for i in range(14):
        d = (datetime.now(timezone.utc) - timedelta(days=13 - i)).strftime("%Y-%m-%d")
        r = by_day.get(d)
        activity.append({"day": d, "successful": r["successful"] if r else 0,
                         "no_data": r["no_data"] if r else 0, "failed": r["failed"] if r else 0})

    per_resolver = {}
    for key, meta in resolver_meta.items():
        r = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN category = 'SUCCESS' THEN 1 ELSE 0 END) AS successful,
                   SUM(CASE WHEN category = 'NOERROR_NODATA' THEN 1 ELSE 0 END) AS no_data
            FROM query_attempts WHERE resolver_key = ?
            """,
            (key,),
        ).fetchone()
        t = r["total"] or 0
        s = r["successful"] or 0
        nd = r["no_data"] or 0
        lat_r = _latencies(conn, "AND resolver_key = ?", (key,))
        per_resolver[key] = {
            "name": meta["name"], "short": meta["short"], "ip": meta["ip"], "total": t, "successful": s,
            "no_data": nd, "failed": t - s - nd,
            "failure_rate": round((t - s - nd) / t * 100, 2) if t else None,
            "median_latency_ms": None if not lat_r else round(median(lat_r), 3),
        }

    recent_tests = [_test_row(r) for r in conn.execute(
        "SELECT * FROM tests ORDER BY created_at DESC, id DESC LIMIT 8")]

    return {
        "tests": tests_count,
        "total_queries": total,
        "successful": successful,
        "no_data": no_data,
        "failed": failed,
        "failure_rate": round(failed / total * 100, 2) if total else None,
        "median_latency_ms": None if not lat else round(median(lat), 3),
        "mean_latency_ms": None if not lat else round(sum(lat) / len(lat), 3),
        "first_observation": row["first_ts"],
        "last_observation": row["last_ts"],
        "resolver_health": health,
        "health_window": health_window,
        "per_resolver": per_resolver,
        "activity": activity,
        "recent_tests": recent_tests,
    }


LATENCY_BUCKETS = [(0, 10), (10, 20), (20, 50), (50, 100), (100, 200), (200, 500), (500, None)]


def analytics(conn, resolver_meta: dict) -> dict:
    """Historical aggregates for the Performance Analytics page."""
    by_type = {}
    for rtype in ("A", "AAAA"):
        by_type[rtype] = {}
        for key in resolver_meta:
            r = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN category = 'SUCCESS' THEN 1 ELSE 0 END) AS successful,
                       SUM(CASE WHEN category = 'NOERROR_NODATA' THEN 1 ELSE 0 END) AS no_data
                FROM query_attempts WHERE resolver_key = ? AND record_type = ?
                """,
                (key, rtype),
            ).fetchone()
            t, s, nd = r["total"] or 0, r["successful"] or 0, r["no_data"] or 0
            lat = _latencies(conn, "AND resolver_key = ? AND record_type = ?", (key, rtype))
            by_type[rtype][key] = {
                "total": t, "successful": s, "no_data": nd, "failed": t - s - nd,
                "failure_rate": round((t - s - nd) / t * 100, 2) if t else None,
                "median_latency_ms": None if not lat else round(median(lat), 3),
            }

    distribution = {}
    for key in resolver_meta:
        lat = _latencies(conn, "AND resolver_key = ?", (key,))
        counts = []
        for lo, hi in LATENCY_BUCKETS:
            counts.append(sum(1 for v in lat if v >= lo and (hi is None or v < hi)))
        distribution[key] = counts
    labels = [f"{lo}–{hi} ms" if hi is not None else f"≥{lo} ms" for lo, hi in LATENCY_BUCKETS]

    categories = {r["category"]: r["n"] for r in conn.execute(
        "SELECT category, COUNT(*) AS n FROM query_attempts GROUP BY category")}

    # Median per test per resolver, for a trend line over the last 30 tests.
    trend_rows = conn.execute(
        "SELECT id, domain, record_type, created_at FROM tests ORDER BY created_at DESC, id DESC LIMIT 30"
    ).fetchall()[::-1]
    trend = []
    for t in trend_rows:
        point = {"id": t["id"], "domain": t["domain"], "record_type": t["record_type"], "created_at": t["created_at"]}
        for key in resolver_meta:
            lat = _latencies(conn, "AND test_id = ? AND resolver_key = ?", (t["id"], key))
            point[key] = None if not lat else round(median(lat), 3)
        trend.append(point)

    return {
        "by_record_type": by_type,
        "distribution": {"labels": labels, "series": distribution},
        "categories": categories,
        "trend": trend,
        "total_queries": sum(categories.values()),
    }
