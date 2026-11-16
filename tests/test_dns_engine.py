"""DNS query engine and response classification (mocked transport, no network)."""
import dns.flags
import dns.message
import pytest

from dns_engine import DNSQueryEngine, resolve_selection
from dns_engine import response_classifier as rc
from dns_engine.resolver import UnknownResolverError, get_resolver


# 1. Valid A record lookup
def test_valid_a_record(engine, google):
    a = engine.query_once("example.com", "A", google, timeout=1)
    assert a.category == rc.SUCCESS
    assert a.success is True and a.outcome == rc.OUTCOME_SUCCESS
    assert a.rcode == "NOERROR"
    assert a.records == ["192.0.2.1"]
    assert a.ttl == 3600
    assert a.resolver_ip == "8.8.8.8" and a.resolver_name == "Google Public DNS"
    assert a.latency_ms is not None and a.latency_ms >= 0
    assert a.transport == "UDP" and a.tcp_fallback is False
    assert a.timestamp.endswith("+00:00")


# 2. Valid AAAA record lookup
def test_valid_aaaa_record(engine, cloudflare):
    a = engine.query_once("example.com", "AAAA", cloudflare, timeout=1)
    assert a.category == rc.SUCCESS
    assert a.records == ["2001:db8::1"]
    assert a.resolver_ip == "1.1.1.1"


def test_cname_chain_is_followed(engine, google):
    a = engine.query_once("www.example.com", "A", google, timeout=1)
    assert a.category == rc.SUCCESS
    assert a.records == ["192.0.2.10", "192.0.2.11"]
    assert a.cname_chain == [{"name": "www.example.com", "target": "edge.cdn.example.net", "ttl": 300}]
    assert a.ttl == 60  # TTL of the final A RRset, not of the CNAME


def test_cname_without_final_record_is_not_success(engine, google):
    a = engine.query_once("cnameonly.example.com", "A", google, timeout=1)
    assert a.category == rc.NODATA
    assert a.success is False
    assert a.records == []
    assert a.cname_chain[0]["target"] == "target.example.net"


def test_answer_for_unrelated_owner_is_not_success(engine, google):
    a = engine.query_once("unrelated.example.com", "A", google, timeout=1)
    assert a.category == rc.NODATA
    assert a.records == []


# 3. NXDOMAIN classification
def test_nxdomain_classification(engine, google):
    a = engine.query_once("nx-missing.example.com", "A", google, timeout=1)
    assert a.category == rc.NXDOMAIN
    assert a.rcode == "NXDOMAIN"
    assert a.success is False and a.outcome == rc.OUTCOME_FAILURE


# 4. NOERROR without requested records
def test_noerror_without_requested_record(engine, google):
    a = engine.query_once("ipv4only.example.com", "AAAA", google, timeout=1)
    assert a.rcode == "NOERROR"
    assert a.category == rc.NODATA
    assert a.outcome == rc.OUTCOME_NODATA
    assert a.success is False
    assert a.records == []


# 5. SERVFAIL classification
def test_servfail_classification(engine, google):
    a = engine.query_once("servfail.example.com", "A", google, timeout=1)
    assert a.category == rc.SERVFAIL and a.rcode == "SERVFAIL" and a.success is False


def test_refused_and_other_rcodes(engine, google):
    assert engine.query_once("refused.example.com", "A", google, 1).category == rc.REFUSED
    other = engine.query_once("formerr.example.com", "A", google, 1)
    assert other.category == rc.OTHER_ERROR and other.rcode == "FORMERR"


# 6. Timeout handling
def test_timeout_is_recorded_as_failure(engine, google):
    a = engine.query_once("timeout.example.com", "A", google, timeout=0.5)
    assert a.category == rc.TIMEOUT
    assert a.success is False and a.outcome == rc.OUTCOME_FAILURE
    assert a.rcode is None
    assert "0.5" in a.error


def test_network_error_is_handled(engine, google):
    a = engine.query_once("netdown.example.com", "A", google, timeout=1)
    assert a.category == rc.NETWORK_ERROR
    assert a.success is False
    assert "Network" in a.error


def test_truncated_udp_falls_back_to_tcp(engine, google, mock_dns):
    a = engine.query_once("truncated.example.com", "A", google, timeout=1)
    assert a.category == rc.SUCCESS
    assert a.tcp_fallback is True and a.transport == "TCP"
    transports = [c[3] for c in mock_dns.calls if c[1] == "truncated.example.com."]
    assert transports == ["udp", "tcp"]


def test_latency_uses_injected_clock(google, mock_dns):
    ticks = iter([10.0, 10.0234])  # perf_counter readings, seconds
    eng = DNSQueryEngine(udp=mock_dns.udp, tcp=mock_dns.tcp, clock=lambda: next(ticks))
    a = eng.query_once("example.com", "A", google, timeout=1)
    assert a.latency_ms == pytest.approx(23.4, abs=1e-6)


def test_query_message_requests_recursion(google):
    seen = {}

    def udp(query, where, **kw):
        seen["rd"] = bool(query.flags & dns.flags.RD)
        seen["edns"] = query.edns
        seen["where"] = where
        seen["port"] = kw.get("port")
        return dns.message.make_response(query)

    DNSQueryEngine(udp=udp).query_once("example.com", "A", google, 1)
    assert seen == {"rd": True, "edns": 0, "where": "8.8.8.8", "port": 53}


def test_run_test_uses_identical_parameters(engine, mock_dns):
    endpoints = resolve_selection("both")
    results = engine.run_test("example.com", "AAAA", endpoints, attempts=5, timeout=1, pause_s=0)
    assert list(results) == ["google", "cloudflare"]
    for key, attempts in results.items():
        assert [a.attempt for a in attempts] == [1, 2, 3, 4, 5]
        assert {a.domain for a in attempts} == {"example.com"}
        assert {a.record_type for a in attempts} == {"AAAA"}
    per_ip = {}
    for ip, *_ in mock_dns.calls:
        per_ip[ip] = per_ip.get(ip, 0) + 1
    assert per_ip == {"8.8.8.8": 5, "1.1.1.1": 5}


def test_progress_callback_called_per_attempt(engine):
    seen = []
    engine.run_test("example.com", "A", resolve_selection("both"), 3, 1, on_attempt=seen.append, pause_s=0)
    assert len(seen) == 6


def test_resolver_allow_list():
    assert get_resolver("google").ip == "8.8.8.8"
    assert get_resolver("cloudflare").ip == "1.1.1.1"
    for bad in ("8.8.4.4", "9.9.9.9", "", None, "GOOGLE"):
        with pytest.raises(UnknownResolverError):
            get_resolver(bad)
    assert [r.key for r in resolve_selection(["cloudflare", "google", "google"])] == ["google", "cloudflare"]
