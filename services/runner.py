"""
Test orchestration: run the DNS engine, then the comparison, performance and
diagnostic modules, and assemble one result document (the flow chart in the
synopsis, step by step).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable

from diagnostics import diagnose_test, outcome_label
from dns_engine import DNSQueryEngine, compare_resolvers, overall_summary
from dns_engine.validation import DNSTestRequest


def run_dns_test(req: DNSTestRequest, engine: DNSQueryEngine,
                 on_attempt: Callable[[dict], None] | None = None) -> dict:
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    def cb(attempt):
        if on_attempt:
            on_attempt(attempt.to_dict())

    raw = engine.run_test(req.domain, req.record_type, req.resolvers, req.attempts, req.timeout, on_attempt=cb)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    attempts = {key: [a.to_dict() for a in lst] for key, lst in raw.items()}
    resolver_meta = {r.key: r.to_dict() for r in req.resolvers}
    comparison = compare_resolvers(attempts, resolver_meta)
    overall = overall_summary(attempts)

    result = {
        "id": None,
        "domain": req.domain,
        "record_type": req.record_type,
        "timeout": req.timeout,
        "attempts_per_resolver": req.attempts,
        "resolver_keys": req.resolver_keys,
        "resolver_meta": resolver_meta,
        "started_at": started.isoformat(timespec="milliseconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "duration_ms": round(duration_ms, 2),
        "attempts": attempts,
        "comparison": comparison,
        "overall": overall,
    }
    result["diagnosis"] = diagnose_test(result)
    result["outcome"] = outcome_label(result)
    return result
