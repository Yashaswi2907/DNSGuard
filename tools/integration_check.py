"""
Quick real-network check: sends real queries to both resolvers and prints what came back.

    python -m tools.integration_check
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dns_engine import DNSQueryEngine, list_resolvers  # noqa: E402

CASES = [("example.com", "A"), ("google.com", "AAAA"), ("www.wikipedia.org", "A"), ("dnsguard-check.invalid", "A")]

if __name__ == "__main__":
    engine = DNSQueryEngine()
    for domain, rtype in CASES:
        for r in list_resolvers():
            a = engine.query_once(domain, rtype, r, timeout=3)
            recs = ", ".join(a.records[:3]) or "-"
            lat = f"{a.latency_ms:8.2f} ms" if a.latency_ms is not None else "       -   "
            print(f"{domain:26} {rtype:4} {r.short:10} {a.category:15} {lat}  {recs}  {a.error or ''}")
