"""
DNS query engine.

Sends real DNS queries with dnspython directly to a configured recursive
resolver and times each exchange with ``time.perf_counter()``.

Why low-level ``dns.query.udp`` instead of ``dns.resolver.Resolver``?
``Resolver.resolve`` hides protocol details: on SERVFAIL it raises
``NoNameservers`` and retries, and it caches answers. For a diagnostic tool we
want the *actual* response code of a *single* exchange, the raw answer section
(to show the CNAME chain), the header flags, and an honest timing - so we build
the query message ourselves and send exactly one request per attempt.

Transport: DNS normally uses UDP port 53. If the resolver sets the TC
(truncated) flag, the query is retried over TCP port 53 as RFC 1035 / RFC 7766
require, and the attempt is marked as a TCP fallback.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rdatatype

from . import response_classifier as rc
from .resolver import ResolverEndpoint

EDNS_PAYLOAD = 1232  # DNS Flag Day 2020 recommended UDP payload size


@dataclass
class QueryAttempt:
    attempt: int
    domain: str
    resolver_key: str
    resolver_name: str
    resolver_ip: str
    record_type: str
    category: str
    outcome: str
    success: bool
    rcode: str | None
    records: list[str] = field(default_factory=list)
    cname_chain: list[dict] = field(default_factory=list)
    ttl: int | None = None
    latency_ms: float | None = None
    transport: str = "UDP"
    tcp_fallback: bool = False
    flags: list[str] = field(default_factory=list)
    timestamp: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["category_label"] = rc.CATEGORY_LABELS.get(self.category, self.category)
        return data


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DNSQueryEngine:
    """
    Executes DNS queries. The transport functions and the clock are injectable
    so the automated tests can supply deterministic mocked responses without
    any network access.
    """

    def __init__(
        self,
        udp: Callable = dns.query.udp,
        tcp: Callable = dns.query.tcp,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self._udp = udp
        self._tcp = tcp
        self._clock = clock

    # ------------------------------------------------------------------ single
    def query_once(
        self,
        domain: str,
        record_type: str,
        endpoint: ResolverEndpoint,
        timeout: float,
        attempt: int = 1,
    ) -> QueryAttempt:
        rdtype = dns.rdatatype.from_text(record_type)
        query = dns.message.make_query(domain, rdtype, use_edns=0, payload=EDNS_PAYLOAD)
        # make_query sets RD (recursion desired): we ask the resolver to do the
        # full recursive resolution on our behalf.

        common = dict(
            attempt=attempt,
            domain=domain,
            resolver_key=endpoint.key,
            resolver_name=endpoint.name,
            resolver_ip=endpoint.ip,
            record_type=record_type,
            timestamp=_now_iso(),
        )

        transport = "UDP"
        tcp_fallback = False
        start = self._clock()
        try:
            response = self._udp(query, endpoint.ip, timeout=timeout, port=endpoint.port,
                                 ignore_unexpected=True)
            if response.flags & dns.flags.TC:
                # Truncated: retry over TCP within the remaining time budget.
                tcp_fallback = True
                transport = "TCP"
                remaining = max(timeout - (self._clock() - start), 0.05)
                response = self._tcp(query, endpoint.ip, timeout=remaining, port=endpoint.port)
            elapsed_ms = (self._clock() - start) * 1000.0
        except dns.exception.Timeout:
            elapsed_ms = (self._clock() - start) * 1000.0
            return QueryAttempt(
                **common,
                category=rc.TIMEOUT,
                outcome=rc.OUTCOME_FAILURE,
                success=False,
                rcode=None,
                latency_ms=round(elapsed_ms, 3),
                transport=transport,
                tcp_fallback=tcp_fallback,
                error=f"No response from {endpoint.ip} within {timeout:g} s",
            )
        except (OSError, EOFError) as exc:
            elapsed_ms = (self._clock() - start) * 1000.0
            return QueryAttempt(
                **common,
                category=rc.NETWORK_ERROR,
                outcome=rc.OUTCOME_FAILURE,
                success=False,
                rcode=None,
                latency_ms=round(elapsed_ms, 3),
                transport=transport,
                tcp_fallback=tcp_fallback,
                error=f"Network error: {type(exc).__name__}"
                      + (f" ({exc.strerror})" if getattr(exc, "strerror", None) else ""),
            )
        except dns.exception.DNSException as exc:
            elapsed_ms = (self._clock() - start) * 1000.0
            return QueryAttempt(
                **common,
                category=rc.OTHER_ERROR,
                outcome=rc.OUTCOME_FAILURE,
                success=False,
                rcode=None,
                latency_ms=round(elapsed_ms, 3),
                transport=transport,
                tcp_fallback=tcp_fallback,
                error=f"Malformed or unexpected DNS response ({type(exc).__name__})",
            )

        classified = rc.classify_response(response, domain, record_type)
        return QueryAttempt(
            **common,
            category=classified.category,
            outcome=classified.outcome,
            success=classified.success,
            rcode=classified.rcode,
            records=classified.records,
            cname_chain=classified.cname_chain,
            ttl=classified.ttl,
            latency_ms=round(elapsed_ms, 3),
            transport=transport,
            tcp_fallback=tcp_fallback,
            flags=classified.flags,
        )

    # ------------------------------------------------------------------ series
    def run_series(
        self,
        domain: str,
        record_type: str,
        endpoint: ResolverEndpoint,
        attempts: int,
        timeout: float,
        on_attempt: Callable[[QueryAttempt], None] | None = None,
        pause_s: float = 0.0,
    ) -> list[QueryAttempt]:
        """Run ``attempts`` sequential queries against one resolver."""
        results = []
        for i in range(1, attempts + 1):
            result = self.query_once(domain, record_type, endpoint, timeout, attempt=i)
            results.append(result)
            if on_attempt:
                on_attempt(result)
            if pause_s and i < attempts:
                time.sleep(pause_s)
        return results

    def run_test(
        self,
        domain: str,
        record_type: str,
        endpoints: list[ResolverEndpoint],
        attempts: int,
        timeout: float,
        on_attempt: Callable[[QueryAttempt], None] | None = None,
        parallel: bool = True,
        pause_s: float = 0.05,
    ) -> dict[str, list[QueryAttempt]]:
        """
        Test every selected resolver with the *same* domain, record type,
        timeout and number of attempts. Resolvers run in parallel (one worker
        each); attempts against a single resolver are sequential so that one
        measurement does not overlap another to the same server.
        """
        lock = threading.Lock()

        def safe_cb(attempt: QueryAttempt):
            if on_attempt:
                with lock:
                    on_attempt(attempt)

        if parallel and len(endpoints) > 1:
            with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
                futures = {
                    ep.key: pool.submit(self.run_series, domain, record_type, ep, attempts, timeout,
                                        safe_cb, pause_s)
                    for ep in endpoints
                }
                return {key: fut.result() for key, fut in futures.items()}
        return {
            ep.key: self.run_series(domain, record_type, ep, attempts, timeout, safe_cb, pause_s)
            for ep in endpoints
        }
