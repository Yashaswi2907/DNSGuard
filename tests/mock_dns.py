"""
Deterministic mocked DNS transport for automated tests.

It builds genuine ``dns.message`` response objects (so the real classifier and
CNAME-chain logic are exercised) but never touches the network. All addresses
come from the documentation ranges reserved by RFC 5737 (192.0.2.0/24,
198.51.100.0/24) and RFC 3849 (2001:db8::/32), so mocked results can never be
mistaken for real measurements.
"""
from __future__ import annotations

import random
import threading
import time

import dns.exception
import dns.flags
import dns.message
import dns.rcode
import dns.rdatatype
import dns.rrset

GOOGLE, CLOUDFLARE = "8.8.8.8", "1.1.1.1"


def _response(query, rcode=dns.rcode.NOERROR, answers=(), truncated=False):
    resp = dns.message.make_response(query)
    resp.flags |= dns.flags.RA
    resp.set_rcode(rcode)
    for name, ttl, rtype, values in answers:
        resp.answer.append(dns.rrset.from_text(name, ttl, "IN", rtype, *values))
    if truncated:
        resp.flags |= dns.flags.TC
        resp.answer = []
    return resp


class MockDNS:
    """
    A callable pair (udp, tcp) compatible with dns.query.udp / dns.query.tcp.

    ``latency`` maps resolver IP -> (base_ms, jitter_ms); when set, each reply
    sleeps for that long so latency charts have something to show.
    """

    def __init__(self, latency: dict | None = None, seed: int = 7):
        self.latency = latency or {}
        self.calls: list[tuple] = []
        self._counters: dict = {}
        self._lock = threading.Lock()
        self._rng = random.Random(seed)

    def _count(self, key) -> int:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
            return self._counters[key]

    def _delay(self, ip, first: bool):
        if ip in self.latency:
            base, jitter = self.latency[ip]
            with self._lock:
                ms = max(0.5, self._rng.gauss(base, jitter))
            if first:
                ms *= 3.2  # first query to a name: cache miss
            time.sleep(ms / 1000.0)

    # ------------------------------------------------------------ transports
    def udp(self, query, where, timeout=None, port=53, **kwargs):
        return self._answer(query, where, "udp")

    def tcp(self, query, where, timeout=None, port=53, **kwargs):
        return self._answer(query, where, "tcp")

    def _answer(self, query, ip, transport):
        q = query.question[0]
        name = q.name.to_text()
        rtype = dns.rdatatype.to_text(q.rdtype)
        n = self._count((ip, name, rtype, transport))
        self.calls.append((ip, name, rtype, transport))
        base = name.rstrip(".")

        if base.startswith("timeout."):
            raise dns.exception.Timeout
        if base.startswith("netdown."):
            raise OSError(101, "Network is unreachable")
        if base.startswith("flaky."):
            if n % 3 == 0:
                raise dns.exception.Timeout
        if base.startswith("cftimeout.") and ip == CLOUDFLARE:
            raise dns.exception.Timeout

        self._delay(ip, first=(n == 1))

        if base.startswith(("nx", "doesnotexist", "no-such")) or base.endswith(".invalid"):
            return _response(query, dns.rcode.NXDOMAIN)
        if base.startswith("servfail."):
            return _response(query, dns.rcode.SERVFAIL)
        if base.startswith("gservfail.") and ip == GOOGLE:
            return _response(query, dns.rcode.SERVFAIL)
        if base.startswith("refused."):
            return _response(query, dns.rcode.REFUSED)
        if base.startswith("formerr."):
            return _response(query, dns.rcode.FORMERR)
        if base.startswith("truncated.") and transport == "udp":
            return _response(query, truncated=True)
        if base.startswith("cnameonly."):
            return _response(query, answers=[(name, 300, "CNAME", ["target.example.net."])])
        if base.startswith("www."):
            target = "edge.cdn.example.net."
            recs = {"A": ["192.0.2.10", "192.0.2.11"], "AAAA": ["2001:db8::10", "2001:db8::11"]}[rtype]
            return _response(query, answers=[(name, 300, "CNAME", [target]), (target, 60, rtype, recs)])
        if base.startswith("ipv4only.") and rtype == "AAAA":
            return _response(query)  # NOERROR / NODATA
        if base.startswith("differ."):
            rec = {"A": "198.51.100.20" if ip == GOOGLE else "198.51.100.21",
                   "AAAA": "2001:db8::20" if ip == GOOGLE else "2001:db8::21"}[rtype]
            return _response(query, answers=[(name, 120, rtype, [rec])])
        if base.startswith("unrelated."):
            # Answer RRset owned by a different name: must NOT count as success.
            return _response(query, answers=[("other.example.org.", 60, rtype,
                                              ["192.0.2.99" if rtype == "A" else "2001:db8::99"])])

        rec = {"A": ["192.0.2.1"], "AAAA": ["2001:db8::1"]}[rtype]
        return _response(query, answers=[(name, 3600, rtype, rec)])
