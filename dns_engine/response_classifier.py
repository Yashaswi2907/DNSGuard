"""
DNS response classification.

Maps a raw DNS response message (or the absence of one) onto the outcome
categories DNSGuard reports. The rules follow RFC 1035 response codes and
RFC 2308 "NODATA" semantics:

* NOERROR + an RRset of the requested type for the query name (following any
  CNAME chain)                                  -> SUCCESS
* NOERROR + no RRset of the requested type      -> NOERROR_NODATA
  (the name exists, or a CNAME was followed, but there is no A/AAAA record)
* NXDOMAIN (rcode 3)                            -> NXDOMAIN
* SERVFAIL (rcode 2)                            -> SERVFAIL
* REFUSED  (rcode 5)                            -> REFUSED
* any other rcode (FORMERR, NOTIMP, ...)        -> OTHER_ERROR
* no response within the timeout               -> TIMEOUT
* socket / transport failure                    -> NETWORK_ERROR
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

import dns.flags
import dns.message
import dns.name
import dns.rcode
import dns.rdatatype

SUCCESS = "SUCCESS"
NODATA = "NOERROR_NODATA"
NXDOMAIN = "NXDOMAIN"
SERVFAIL = "SERVFAIL"
REFUSED = "REFUSED"
TIMEOUT = "TIMEOUT"
NETWORK_ERROR = "NETWORK_ERROR"
OTHER_ERROR = "OTHER_ERROR"

ALL_CATEGORIES = (SUCCESS, NODATA, NXDOMAIN, SERVFAIL, REFUSED, TIMEOUT, NETWORK_ERROR, OTHER_ERROR)

# Three-way outcome used by the performance module.
#  success  -> usable record(s) returned
#  no_data  -> valid NOERROR response, but no record of the requested type
#  failure  -> classified DNS error or no response (counts toward failure rate)
OUTCOME_SUCCESS = "success"
OUTCOME_NODATA = "no_data"
OUTCOME_FAILURE = "failure"

CATEGORY_OUTCOME = {
    SUCCESS: OUTCOME_SUCCESS,
    NODATA: OUTCOME_NODATA,
    NXDOMAIN: OUTCOME_FAILURE,
    SERVFAIL: OUTCOME_FAILURE,
    REFUSED: OUTCOME_FAILURE,
    TIMEOUT: OUTCOME_FAILURE,
    NETWORK_ERROR: OUTCOME_FAILURE,
    OTHER_ERROR: OUTCOME_FAILURE,
}

CATEGORY_LABELS = {
    SUCCESS: "NOERROR with records",
    NODATA: "NOERROR, no requested record",
    NXDOMAIN: "NXDOMAIN",
    SERVFAIL: "SERVFAIL",
    REFUSED: "REFUSED",
    TIMEOUT: "Timeout",
    NETWORK_ERROR: "Network error",
    OTHER_ERROR: "Other DNS error",
}

MAX_CNAME_HOPS = 16


@dataclass
class ClassifiedResponse:
    category: str
    rcode: str
    records: list[str] = field(default_factory=list)
    cname_chain: list[dict] = field(default_factory=list)
    ttl: int | None = None
    answer_count: int = 0
    authority_count: int = 0
    flags: list[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        return CATEGORY_OUTCOME[self.category]

    @property
    def success(self) -> bool:
        return self.category == SUCCESS


def outcome_of(category: str) -> str:
    return CATEGORY_OUTCOME.get(category, OUTCOME_FAILURE)


def follow_answer(message: dns.message.Message, qname: dns.name.Name, rdtype: int):
    """
    Walk the answer section starting from ``qname``, following CNAMEs.

    Returns (records, cname_chain, ttl). Records are only taken from the RRset
    owned by the *final* name in the chain, so an answer section that holds
    only a CNAME (or records for an unrelated owner) yields no records.
    """
    current = qname
    chain: list[dict] = []
    visited = {current}

    for _ in range(MAX_CNAME_HOPS):
        cname_rrset = None
        for rrset in message.answer:
            if rrset.name == current and rrset.rdtype == dns.rdatatype.CNAME:
                cname_rrset = rrset
                break
        if cname_rrset is None:
            break
        target = cname_rrset[0].target
        chain.append({
            "name": current.to_text(omit_final_dot=True),
            "target": target.to_text(omit_final_dot=True),
            "ttl": cname_rrset.ttl,
        })
        if target in visited:  # CNAME loop - stop following
            break
        visited.add(target)
        current = target

    records: list[str] = []
    ttl = None
    for rrset in message.answer:
        if rrset.name == current and rrset.rdtype == rdtype:
            records.extend(rd.to_text() for rd in rrset)
            ttl = rrset.ttl if ttl is None else min(ttl, rrset.ttl)

    # Normalise: unique, sorted (makes cross-resolver comparison order-independent)
    records = sorted(set(records), key=_sort_key)
    return records, chain, ttl


def _sort_key(addr: str):
    try:
        ip = ipaddress.ip_address(addr)
        return (ip.version, int(ip))
    except ValueError:
        return (9, 0)


def classify_response(message: dns.message.Message, qname: str, record_type: str) -> ClassifiedResponse:
    """Classify a DNS response message for the given query name and type."""
    name = dns.name.from_text(qname)
    rdtype = dns.rdatatype.from_text(record_type)
    rcode = message.rcode()
    rcode_text = dns.rcode.to_text(rcode)

    records, chain, ttl = follow_answer(message, name, rdtype)
    flags = dns.flags.to_text(message.flags).split()

    base = dict(
        rcode=rcode_text,
        cname_chain=chain,
        answer_count=sum(len(r) for r in message.answer),
        authority_count=sum(len(r) for r in message.authority),
        flags=flags,
    )

    if rcode == dns.rcode.NOERROR:
        if records:
            return ClassifiedResponse(category=SUCCESS, records=records, ttl=ttl, **base)
        return ClassifiedResponse(category=NODATA, **base)
    if rcode == dns.rcode.NXDOMAIN:
        return ClassifiedResponse(category=NXDOMAIN, **base)
    if rcode == dns.rcode.SERVFAIL:
        return ClassifiedResponse(category=SERVFAIL, **base)
    if rcode == dns.rcode.REFUSED:
        return ClassifiedResponse(category=REFUSED, **base)
    return ClassifiedResponse(category=OTHER_ERROR, **base)
