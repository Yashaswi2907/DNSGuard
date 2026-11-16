# DNSGuard API reference

Base URL: `http://127.0.0.1:5000`. All API responses are JSON with one of two shapes:

```json
{ "ok": true,  "data": { ... } }
{ "ok": false, "error": { "code": "validation_error", "message": "…", "field": "domain" } }
```

| HTTP status | When |
|---|---|
| 200 | Success |
| 202 | Async test accepted (`async: true`) |
| 400 | Invalid JSON, validation error, or missing confirmation |
| 403 | Missing or invalid CSRF token |
| 404 | Unknown test, job or route |
| 405 | Wrong method |
| 429 | Rate limit reached or too many running jobs |
| 500 | Unexpected error (generic message, details only in the server log) |

### CSRF

Every `POST` and `DELETE` to `/api/*` must send `X-CSRF-Token`. The token is in each page's `<meta name="csrf-token">` and is bound to the session cookie. In the test configuration (`TestConfig`) CSRF checking is switched off.

```bash
# Example with curl: fetch a page to get the cookie and token, then call the API
curl -s -c jar.txt http://127.0.0.1:5000/diagnostics | grep -o 'csrf-token" content="[^"]*' | cut -d'"' -f3 > token.txt
curl -s -b jar.txt -H "Content-Type: application/json" -H "X-CSRF-Token: $(cat token.txt)" \
     -d '{"domain":"example.com","record_type":"A","resolvers":"both","attempts":5,"timeout":2}' \
     http://127.0.0.1:5000/api/dns/resolve
```

---

## POST /api/dns/resolve

Run a DNS test. By default it runs synchronously and is saved to history.

| Field | Type | Allowed values | Default |
|---|---|---|---|
| `domain` | string | Domain name. A pasted URL is reduced to its host; IDN names are IDNA-encoded. IP addresses are rejected. | required |
| `record_type` | string | `A`, `AAAA` | `A` |
| `resolvers` | string or list | `google`, `cloudflare`, `both`, or `["google","cloudflare"]` | `both` |
| `attempts` | int | 1, 3, 5, 10, 20 (per resolver) | 3 |
| `timeout` | number | 0.5 – 10 seconds | 2 |
| `async` | bool | `true` returns `202` with a `job_id` to poll | `false` |
| `save` | bool | `false` skips storing the result | `true` |

Fields such as `resolver_ip`, `nameserver` or `server` are rejected: only the configured resolvers can be queried.

**Response `data` (abridged):**

```json
{
  "id": 1,
  "domain": "www.example.com",
  "record_type": "A",
  "timeout": 2.0,
  "attempts_per_resolver": 3,
  "resolver_keys": ["google", "cloudflare"],
  "resolver_meta": { "google": { "name": "Google Public DNS", "ip": "8.8.8.8", "...": "..." } },
  "started_at": "2026-11-16T17:45:59.117+00:00",
  "duration_ms": 106.15,
  "attempts": { "google": [ /* attempt objects */ ], "cloudflare": [ /* … */ ] },
  "comparison": { "resolvers": { "google": { "summary": { /* … */ } } }, "faster": {}, "record_consistency": {}, "observations": [] },
  "overall": { /* summary across both resolvers */ },
  "diagnosis": { "severity": "ok", "headline": "…", "resolvers": {}, "cross_resolver": [], "disclaimer": "…" },
  "outcome": "SUCCESS"
}
```

**Attempt object** (one per query sent):

```json
{
  "attempt": 1,
  "domain": "www.example.com",
  "resolver_key": "google",
  "resolver_name": "Google Public DNS",
  "resolver_ip": "8.8.8.8",
  "record_type": "A",
  "category": "SUCCESS",
  "outcome": "success",
  "success": true,
  "rcode": "NOERROR",
  "records": ["192.0.2.10", "192.0.2.11"],
  "cname_chain": [{ "name": "www.example.com", "target": "edge.cdn.example.net", "ttl": 300 }],
  "ttl": 60,
  "latency_ms": 2.381,
  "transport": "UDP",
  "tcp_fallback": false,
  "flags": ["QR", "RD", "RA"],
  "timestamp": "2026-11-16T17:45:59.117+00:00",
  "error": null,
  "category_label": "NOERROR with records"
}
```

`category` is one of `SUCCESS`, `NOERROR_NODATA`, `NXDOMAIN`, `SERVFAIL`, `REFUSED`, `OTHER_ERROR`, `TIMEOUT`, `NETWORK_ERROR`. `rcode` is `null` when no response was received.

**Per-resolver summary** (`comparison.resolvers.<key>.summary`):

```json
{
  "total": 3, "successful": 3, "no_data": 0, "failed": 0,
  "failure_rate": 0.0, "success_rate": 100.0,
  "latency_samples": 3, "median_latency_ms": 0.327, "mean_latency_ms": 0.999,
  "min_latency_ms": 0.288, "max_latency_ms": 2.381, "stdev_latency_ms": 1.197,
  "category_counts": { "SUCCESS": 3 }, "dominant_category": "SUCCESS", "mixed_outcomes": false,
  "records": ["192.0.2.10", "192.0.2.11"], "distinct_record_sets": 1,
  "cname_chain": [ … ], "ttl_min": 60, "ttl_max": 60, "timeouts": 0, "tcp_fallbacks": 0
}
```

**Comparison fields:**

```json
{
  "faster": { "key": "cloudflare", "name": "Cloudflare DNS", "tie": false, "margin_ms": 9.68, "margin_pct": 47.5 },
  "latency_note": "Cloudflare DNS had the lower median latency in this test (…). This reflects this network, time and sample only — it is not a general ranking of the resolvers.",
  "record_consistency": { "status": "identical", "common": ["192.0.2.10", "192.0.2.11"], "only_a": [], "only_b": [], "note": "…", "a": "google", "b": "cloudflare" },
  "status_consistency": { "consistent": true, "a": "SUCCESS", "b": "SUCCESS" }
}
```

`faster` is `null` when either resolver has no successful sample, and `{"tie": true, …}` when the medians differ by less than 0.5 ms.

**Validation error example:**

```json
{ "ok": false, "error": { "code": "validation_error", "message": "Enter a domain name only, for example example.com.", "field": "domain" } }
```

## POST /api/dns/compare

Same body and response as `/api/dns/resolve`, but both resolvers are always queried (the `resolvers` field is ignored).

## GET /api/dns/jobs/<job_id>

Poll an async test.

```json
{
  "id": "3f0c…", "state": "running", "total": 10, "completed": 4, "progress": 40.0,
  "latest": [{ "resolver_key": "google", "attempt": 1, "category": "SUCCESS", "latency_ms": 18.2 }],
  "domain": "example.com", "record_type": "A", "result": null, "error": null
}
```

`state` is `running`, `done` (then `result` holds the full response above) or `error`. Jobs expire 15 minutes after they finish.

## GET /api/dashboard/stats

Totals over every stored attempt (`total_queries`, `successful`, `no_data`, `failed`, `failure_rate`, `median_latency_ms`, `mean_latency_ms`). Also returns `resolver_health` (from the last 50 attempts per resolver: `status` ∈ `operational|degraded|unresponsive|unknown`, `answered_pct`, `median_latency_ms`, `last_seen`), `per_resolver`, `activity` (14 days) and `recent_tests`.

## GET /api/analytics

`by_record_type` (A/AAAA × resolver: totals, failure rate, median), `distribution` (latency histogram per resolver), `categories` (count per outcome), `trend` (median per resolver for the last 30 tests).

## GET /api/history

Query parameters: `q` (domain substring), `from`, `to` (`YYYY-MM-DD` as a UTC day, or a full ISO-8601 timestamp; `to` is exclusive for timestamps), `record_type`, `outcome`, `sort` (`created_at|domain|median|failure_rate|record_type|id`), `order` (`asc|desc`), `limit` (1–500), `offset`.

```json
{ "ok": true, "data": { "total": 1, "limit": 1, "offset": 0, "items": [{
  "id": 1, "domain": "www.example.com", "record_type": "A", "resolvers": ["google", "cloudflare"],
  "attempts": 3, "timeout": 2.0, "created_at": "2026-11-16T17:45:59.117+00:00", "duration_ms": 106.15,
  "total_queries": 6, "successful": 6, "no_data": 0, "failed": 0,
  "median_latency_ms": 0.313, "failure_rate": 0.0, "outcome": "SUCCESS" }] } }
```

`outcome` values: `SUCCESS`, `PARTIAL` (some success, some failure), `FAILED`, or a single category (`NXDOMAIN`, `NOERROR_NODATA`, `SERVFAIL`, `TIMEOUT`, …).

## GET /api/history/<id> and GET /api/history/latest

The list fields plus `comparison`, `diagnosis`, `resolver_meta` and `attempts_by_resolver`.

## DELETE /api/history/<id>

Deletes one test and its attempts. Returns `{"deleted": <id>}`, or `404`.

## DELETE /api/history

Body `{"confirm": true}` is required. Returns `{"deleted": <count>}`.

## GET /api/history/export/csv and /export/json

Download every attempt (CSV) or every test plus attempts (JSON). Add `?test_id=<id>` for a single test. CSV cells that start with `= + - @` are prefixed with `'` to prevent spreadsheet formula injection.

CSV columns: `test_id, test_created_at, domain, record_type, resolver_key, resolver_name, resolver_ip, attempt, category, rcode, success, latency_ms, records, cname_chain, ttl, transport, tcp_fallback, timestamp, error`.

## GET /api/meta, /api/status, /api/diagnostics/rules

Configuration (resolvers, record types, attempts, timeout limits), application/database status, and the diagnostic rule table.
