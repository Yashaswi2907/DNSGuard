"""Rule-based diagnostic engine."""
import pytest

from diagnostics import RULES, diagnose_attempt, diagnose_test, outcome_label
from dns_engine import resolve_selection
from dns_engine import response_classifier as rc
from dns_engine.validation import DNSTestRequest
from services.runner import run_dns_test


def run(engine, domain, rtype="A", attempts=3, resolvers="both"):
    req = DNSTestRequest(domain, rtype, resolve_selection(resolvers), attempts, 1.0)
    return run_dns_test(req, engine)


def test_every_category_has_a_rule_with_required_fields():
    for cat in rc.ALL_CATEGORIES:
        rule = RULES[cat]
        for field in ("status", "title", "severity", "simple", "technical", "checks"):
            assert rule[field], f"{cat} missing {field}"
        assert len(rule["checks"]) >= 2


def test_nxdomain_explanation_matches_spec(engine):
    r = run(engine, "nx-missing.example.com")
    d = r["diagnosis"]["resolvers"]["google"]
    assert d["status"] == "NXDOMAIN"
    assert d["simple"] == "The DNS resolver indicates that this domain name does not exist."
    assert "Verify the domain spelling." in d["checks"]
    assert any("registration" in c for c in d["checks"])
    assert any("another resolver" in c for c in d["checks"])
    cross = r["diagnosis"]["cross_resolver"][0]
    assert cross["title"] == "Both resolvers report NXDOMAIN"
    assert r["outcome"] == "NXDOMAIN"


def test_nodata_is_informational_not_error(engine):
    r = run(engine, "ipv4only.example.com", "AAAA")
    d = r["diagnosis"]["resolvers"]["cloudflare"]
    assert d["category"] == rc.NODATA
    assert d["severity"] == "info"
    assert any("IPv6" in n for n in d["notes"])
    assert "not a resolver failure" in d["technical"]


def test_success_diagnosis_includes_evidence_and_resolver_info(engine):
    r = run(engine, "www.example.com")
    d = r["diagnosis"]["resolvers"]["google"]
    assert d["severity"] == "ok"
    assert d["resolver"]["ip"] == "8.8.8.8"
    assert any("CNAME chain" in n for n in d["notes"])
    assert any("Median latency" in e for e in d["evidence"])
    assert r["diagnosis"]["headline"] == "www.example.com resolved successfully"


def test_servfail_does_not_claim_a_single_root_cause(engine):
    r = run(engine, "servfail.example.com")
    d = r["diagnosis"]["resolvers"]["google"]
    assert d["status"] == "SERVFAIL"
    assert "does not identify which applies" in d["technical"]
    assert r["diagnosis"]["cross_resolver"][0]["title"] == "Both resolvers returned SERVFAIL"
    assert "disclaimer" in r["diagnosis"]


def test_timeout_only_on_one_resolver(engine):
    r = run(engine, "cftimeout.example.com")
    assert r["diagnosis"]["resolvers"]["cloudflare"]["status"] == "TIMEOUT"
    assert r["diagnosis"]["resolvers"]["google"]["status"] == "NOERROR"
    cross = r["diagnosis"]["cross_resolver"][0]
    assert cross["title"] == "Only Cloudflare DNS timed out"
    assert "possible reasons" in cross["text"]
    assert r["outcome"] == "PARTIAL"


def test_intermittent_failures(engine):
    r = run(engine, "flaky.example.com", attempts=10)
    d = r["diagnosis"]["resolvers"]["google"]
    assert d["category"] == "INTERMITTENT"
    assert d["severity"] == "warning"
    assert "cannot establish" in d["technical"]
    assert r["diagnosis"]["headline"] == "Intermittent failures observed"


def test_diagnose_single_attempt():
    d = diagnose_attempt({"category": rc.TIMEOUT, "resolver_name": "Google Public DNS", "resolver_ip": "8.8.8.8",
                          "domain": "example.com", "record_type": "A"}, timeout=2)
    assert d["status"] == "TIMEOUT"
    assert "2 seconds" in d["simple"]
    assert "8.8.8.8:53" in d["technical"]


@pytest.mark.parametrize("domain, expected", [
    ("example.com", "SUCCESS"),
    ("servfail.example.com", "SERVFAIL"),
    ("timeout.example.com", "TIMEOUT"),
    ("gservfail.example.com", "PARTIAL"),
])
def test_outcome_labels(engine, domain, expected):
    assert outcome_label(run(engine, domain)) == expected


def test_diagnose_test_is_deterministic(engine):
    r = run(engine, "example.com")
    assert diagnose_test(r) == diagnose_test(r)
