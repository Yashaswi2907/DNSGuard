"""Performance calculations: median, failure rate, summaries and resolver comparison."""
import statistics

import pytest

from dns_engine import compare_resolvers, failure_rate, median, summarize_attempts
from dns_engine import response_classifier as rc


def att(category, latency=None, records=None, key="google", **extra):
    return {"category": category, "latency_ms": latency, "records": records or [], "resolver_key": key,
            "ttl": extra.get("ttl"), "cname_chain": extra.get("cname_chain", []), "tcp_fallback": False}


# 7. Median latency calculation
@pytest.mark.parametrize("values, expected", [
    ([5.0], 5.0),
    ([3.0, 1.0, 2.0], 2.0),
    ([4.0, 1.0, 3.0, 2.0], 2.5),
    ([10.0, 10.0, 200.0], 10.0),
    ([], None),
])
def test_median(values, expected):
    assert median(values) == expected
    if values:
        assert median(values) == statistics.median(values)


# 8. Failure rate calculation
def test_failure_rate_formula():
    assert failure_rate(0, 10) == 0.0
    assert failure_rate(3, 10) == 30.0
    assert failure_rate(1, 3) == pytest.approx(33.3333, rel=1e-4)
    assert failure_rate(5, 5) == 100.0
    assert failure_rate(0, 0) is None


def test_summary_excludes_timeouts_and_errors_from_latency():
    attempts = [
        att(rc.SUCCESS, 10.0, ["192.0.2.1"]),
        att(rc.SUCCESS, 30.0, ["192.0.2.1"]),
        att(rc.SUCCESS, 20.0, ["192.0.2.1"]),
        att(rc.TIMEOUT, 2000.0),        # must not be a latency sample
        att(rc.SERVFAIL, 5.0),          # failed response: not a sample
        att(rc.NODATA, 4.0),            # no usable record: not a sample
    ]
    s = summarize_attempts(attempts)
    assert s["total"] == 6
    assert s["successful"] == 3
    assert s["no_data"] == 1
    assert s["failed"] == 2
    assert s["successful"] + s["no_data"] + s["failed"] == s["total"]
    assert s["latency_samples"] == 3
    assert s["median_latency_ms"] == 20.0
    assert s["min_latency_ms"] == 10.0 and s["max_latency_ms"] == 30.0
    assert s["failure_rate"] == pytest.approx(33.33, abs=0.01)  # (2 / 6) x 100
    assert s["timeouts"] == 1
    assert s["mixed_outcomes"] is True


def test_summary_with_no_successful_measurements():
    s = summarize_attempts([att(rc.TIMEOUT, 1000.0), att(rc.TIMEOUT, 1000.0)])
    assert s["median_latency_ms"] is None
    assert s["mean_latency_ms"] is None
    assert s["latency_samples"] == 0
    assert s["failure_rate"] == 100.0


def test_summary_empty():
    s = summarize_attempts([])
    assert s["total"] == 0 and s["failure_rate"] is None and s["median_latency_ms"] is None


# 9. Resolver comparison
def test_compare_identifies_lower_median_with_caveat():
    meta = {"google": {"name": "Google Public DNS"}, "cloudflare": {"name": "Cloudflare DNS"}}
    results = {
        "google": [att(rc.SUCCESS, v, ["192.0.2.1"]) for v in (20.0, 22.0, 24.0)],
        "cloudflare": [att(rc.SUCCESS, v, ["192.0.2.1"], key="cloudflare") for v in (10.0, 12.0, 14.0)],
    }
    c = compare_resolvers(results, meta)
    assert c["faster"]["key"] == "cloudflare"
    assert c["faster"]["margin_ms"] == 10.0
    assert c["faster"]["margin_pct"] == pytest.approx(45.5, abs=0.1)
    assert "not a general ranking" in c["latency_note"]
    assert c["record_consistency"]["status"] == "identical"
    assert c["status_consistency"]["consistent"] is True


def test_compare_tie_and_missing_samples():
    tie = compare_resolvers({"google": [att(rc.SUCCESS, 10.0, ["a"])], "cloudflare": [att(rc.SUCCESS, 10.2, ["a"])]})
    assert tie["faster"]["tie"] is True
    none = compare_resolvers({"google": [att(rc.TIMEOUT, 900.0)], "cloudflare": [att(rc.SUCCESS, 5.0, ["a"])]})
    assert none["faster"] is None
    assert "needs successful samples from both" in none["latency_note"]


@pytest.mark.parametrize("ga, cb, status", [
    (["192.0.2.1"], ["192.0.2.1"], "identical"),
    (["192.0.2.1", "192.0.2.2"], ["192.0.2.2", "192.0.2.3"], "overlap"),
    (["192.0.2.1"], ["192.0.2.9"], "different"),
    (["192.0.2.1"], [], "not_comparable"),
])
def test_record_consistency(ga, cb, status):
    results = {
        "google": [att(rc.SUCCESS, 5.0, ga)],
        "cloudflare": [att(rc.SUCCESS if cb else rc.NXDOMAIN, 5.0, cb, key="cloudflare")],
    }
    c = compare_resolvers(results)
    assert c["record_consistency"]["status"] == status
    if status in ("overlap", "different"):
        # reported as an observation, never as an error
        assert any("observation" in o for o in c["observations"])


def test_single_resolver_comparison():
    c = compare_resolvers({"google": [att(rc.SUCCESS, 5.0, ["a"])]})
    assert c["faster"] is None and "Only one resolver" in c["latency_note"]
