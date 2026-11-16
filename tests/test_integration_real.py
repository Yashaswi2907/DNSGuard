"""
Real DNS integration test (uses the network: 8.8.8.8 and 1.1.1.1 on UDP/TCP 53).

Skipped by default so the automated suite never depends on internet access.
Run it on a normal network with:

    DNSGUARD_NETWORK_TESTS=1 python -m pytest tests/test_integration_real.py -v      (macOS/Linux)
    $env:DNSGUARD_NETWORK_TESTS=1; python -m pytest tests/test_integration_real.py -v (PowerShell)
"""
import os

import pytest

from dns_engine import DNSQueryEngine, get_resolver
from dns_engine import response_classifier as rc

pytestmark = pytest.mark.skipif(os.environ.get("DNSGUARD_NETWORK_TESTS") != "1",
                                reason="set DNSGUARD_NETWORK_TESTS=1 to run real DNS queries")


@pytest.mark.parametrize("key", ["google", "cloudflare"])
def test_real_a_lookup(key):
    a = DNSQueryEngine().query_once("example.com", "A", get_resolver(key), timeout=3)
    assert a.category == rc.SUCCESS, f"{key}: {a.category} {a.error}"
    assert a.records and a.latency_ms > 0


@pytest.mark.parametrize("key", ["google", "cloudflare"])
def test_real_nxdomain(key):
    # .invalid is reserved by RFC 6761 and must never resolve.
    a = DNSQueryEngine().query_once("dnsguard-check.invalid", "A", get_resolver(key), timeout=3)
    assert a.category == rc.NXDOMAIN


@pytest.mark.parametrize("key", ["google", "cloudflare"])
def test_real_aaaa_lookup(key):
    a = DNSQueryEngine().query_once("google.com", "AAAA", get_resolver(key), timeout=3)
    assert a.category in (rc.SUCCESS, rc.NODATA)
