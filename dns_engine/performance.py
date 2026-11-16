"""
Performance measurement and resolver comparison.

Definitions (from the project synopsis):

* Query response time  - elapsed time of one attempt, in milliseconds.
* Median latency       - median of response times of SUCCESSFUL attempts only.
                         Timeouts, errors and NODATA answers are excluded.
* Successful count     - attempts that returned a usable record of the
                         requested type (NOERROR + A/AAAA RRset).
* Failure rate         - (failed attempts / total attempts) x 100, where a
                         failed attempt is a classified DNS error (NXDOMAIN,
                         SERVFAIL, REFUSED, other rcode) or no response
                         (timeout / network error).
* NOERROR/NODATA       - a valid "no such record" answer. It is neither a
                         success (no usable record) nor a resolver failure, so
                         it is reported as its own bucket:
                         successful + no_data + failed = total.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Iterable

from . import response_classifier as rc

TIE_THRESHOLD_MS = 0.5


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def median(values: Iterable[float]) -> float | None:
    """Median of a sequence; None for an empty sequence."""
    data = sorted(float(v) for v in values)
    n = len(data)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return data[mid]
    return (data[mid - 1] + data[mid]) / 2.0


def failure_rate(failed: int, total: int) -> float | None:
    """(failed / total) x 100, or None when there were no attempts."""
    if total <= 0:
        return None
    return (failed / total) * 100.0


def _r(value, digits=3):
    return None if value is None else round(value, digits)


def summarize_attempts(attempts: list) -> dict:
    """Aggregate a list of attempts (dicts or QueryAttempt objects) for one resolver."""
    total = len(attempts)
    categories = Counter(_get(a, "category") for a in attempts)
    outcomes = Counter(rc.outcome_of(_get(a, "category")) for a in attempts)

    successful = outcomes.get(rc.OUTCOME_SUCCESS, 0)
    no_data = outcomes.get(rc.OUTCOME_NODATA, 0)
    failed = outcomes.get(rc.OUTCOME_FAILURE, 0)

    samples = [
        float(_get(a, "latency_ms"))
        for a in attempts
        if _get(a, "category") == rc.SUCCESS and _get(a, "latency_ms") is not None
    ]
    med = median(samples)
    mean = sum(samples) / len(samples) if samples else None
    stdev = None
    if len(samples) >= 2:
        stdev = math.sqrt(sum((x - mean) ** 2 for x in samples) / (len(samples) - 1))

    record_union: set[str] = set()
    distinct_sets: list[list[str]] = []
    for a in attempts:
        if _get(a, "category") == rc.SUCCESS:
            recs = sorted(_get(a, "records") or [])
            record_union.update(recs)
            if recs not in distinct_sets:
                distinct_sets.append(recs)

    ttls = [_get(a, "ttl") for a in attempts if _get(a, "ttl") is not None]
    cname_chain = next((_get(a, "cname_chain") for a in attempts if _get(a, "cname_chain")), [])

    dominant = categories.most_common(1)[0][0] if categories else None
    fr = failure_rate(failed, total)

    return {
        "total": total,
        "successful": successful,
        "no_data": no_data,
        "failed": failed,
        "failure_rate": _r(fr, 2),
        "success_rate": _r((successful / total) * 100.0, 2) if total else None,
        "latency_samples": len(samples),
        "median_latency_ms": _r(med),
        "mean_latency_ms": _r(mean),
        "min_latency_ms": _r(min(samples)) if samples else None,
        "max_latency_ms": _r(max(samples)) if samples else None,
        "stdev_latency_ms": _r(stdev),
        "category_counts": dict(categories),
        "dominant_category": dominant,
        "mixed_outcomes": len(categories) > 1,
        "records": sorted(record_union, key=rc._sort_key),
        "distinct_record_sets": len(distinct_sets),
        "cname_chain": cname_chain,
        "ttl_min": min(ttls) if ttls else None,
        "ttl_max": max(ttls) if ttls else None,
        "timeouts": categories.get(rc.TIMEOUT, 0),
        "tcp_fallbacks": sum(1 for a in attempts if _get(a, "tcp_fallback")),
    }


def compare_records(a: list[str], b: list[str]) -> dict:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        status = "not_comparable"
        note = "Record sets cannot be compared because at least one resolver returned no usable records."
    elif sa == sb:
        status = "identical"
        note = "Both resolvers returned the same record set."
    elif sa & sb:
        status = "overlap"
        note = ("The record sets partially overlap. This is commonly seen with load-balanced or "
                "geo-distributed services and is reported as an observation, not an error.")
    else:
        status = "different"
        note = ("The resolvers returned different addresses. Differences can come from caching, "
                "anycast/geo-based answers (e.g. CDNs) or a recent DNS change; this is an observation "
                "and does not by itself indicate a fault.")
    return {
        "status": status,
        "common": sorted(sa & sb, key=rc._sort_key),
        "only_a": sorted(sa - sb, key=rc._sort_key),
        "only_b": sorted(sb - sa, key=rc._sort_key),
        "note": note,
    }


def compare_resolvers(results: dict[str, list], resolver_meta: dict[str, dict] | None = None) -> dict:
    """
    Build a side-by-side comparison of the resolvers in ``results``.
    ``results`` maps resolver key -> list of attempts.
    """
    resolver_meta = resolver_meta or {}
    summaries = {key: summarize_attempts(atts) for key, atts in results.items()}
    keys = list(results.keys())

    comparison = {
        "resolvers": {
            k: {**resolver_meta.get(k, {"key": k}), "summary": summaries[k]} for k in keys
        },
        "faster": None,
        "latency_note": None,
        "latency_caveat": ("Latency depends on your network path, location, time of day and resolver caches, "
                           "so a result from one test is not a general ranking of the resolvers."),
        "record_consistency": None,
        "status_consistency": None,
        "observations": [],
    }

    if len(keys) < 2:
        comparison["latency_note"] = "Only one resolver was tested; select both resolvers to compare."
        return comparison

    a, b = keys[0], keys[1]
    sa, sb = summaries[a], summaries[b]
    name = lambda k: resolver_meta.get(k, {}).get("name", k)  # noqa: E731

    ma, mb = sa["median_latency_ms"], sb["median_latency_ms"]
    if ma is None and mb is None:
        comparison["latency_note"] = "Neither resolver produced a successful measurement, so latency cannot be compared."
    elif ma is None or mb is None:
        only = a if ma is not None else b
        comparison["latency_note"] = (
            f"Only {name(only)} produced successful measurements; a latency comparison needs successful samples from both."
        )
    else:
        diff = abs(ma - mb)
        if diff < TIE_THRESHOLD_MS:
            comparison["latency_note"] = (
                f"Median latencies differ by {diff:.2f} ms, which is below {TIE_THRESHOLD_MS} ms; "
                "treat them as comparable for this test."
            )
            comparison["faster"] = {"key": None, "tie": True, "margin_ms": round(diff, 3)}
        else:
            fast, slow = (a, b) if ma < mb else (b, a)
            fm, sm = min(ma, mb), max(ma, mb)
            comparison["faster"] = {
                "key": fast,
                "name": name(fast),
                "tie": False,
                "margin_ms": round(diff, 3),
                "margin_pct": round((diff / sm) * 100.0, 1) if sm else None,
            }
            comparison["latency_note"] = (
                f"{name(fast)} had the lower median latency in this test ({fm:.2f} ms vs {sm:.2f} ms). "
                "This reflects this network, time and sample only — it is not a general ranking of the resolvers."
            )

    rec = compare_records(sa["records"], sb["records"])
    rec["a"], rec["b"] = a, b
    comparison["record_consistency"] = rec

    same_status = sa["dominant_category"] == sb["dominant_category"]
    comparison["status_consistency"] = {
        "consistent": same_status,
        "a": sa["dominant_category"],
        "b": sb["dominant_category"],
    }

    obs = comparison["observations"]
    if not same_status:
        obs.append(
            f"The resolvers reported different outcomes: {name(a)} → {rc.CATEGORY_LABELS.get(sa['dominant_category'])}, "
            f"{name(b)} → {rc.CATEGORY_LABELS.get(sb['dominant_category'])}."
        )
    if rec["status"] in ("overlap", "different"):
        obs.append(rec["note"])
    for k, s in ((a, sa), (b, sb)):
        if s["mixed_outcomes"]:
            obs.append(f"{name(k)} returned mixed outcomes across attempts ({', '.join(f'{c}×{n}' for c, n in s['category_counts'].items())}).")
        if s["distinct_record_sets"] > 1:
            obs.append(f"{name(k)} returned {s['distinct_record_sets']} different record sets across attempts (rotation or load balancing is common).")
    return comparison


def overall_summary(results: dict[str, list]) -> dict:
    """Summary across every attempt of a test (all resolvers combined)."""
    all_attempts = [a for atts in results.values() for a in atts]
    return summarize_attempts(all_attempts)
