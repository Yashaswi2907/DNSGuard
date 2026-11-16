"""DNSGuard DNS engine: resolver config, querying, classification and performance."""
from .performance import compare_resolvers, median, failure_rate, overall_summary, summarize_attempts
from .query_handler import DNSQueryEngine, QueryAttempt
from .resolver import ResolverEndpoint, get_resolver, list_resolvers, resolve_selection
from .validation import DNSTestRequest, ValidationError, validate_test_request

__all__ = [
    "DNSQueryEngine", "QueryAttempt", "ResolverEndpoint", "get_resolver", "list_resolvers",
    "resolve_selection", "compare_resolvers", "median", "failure_rate", "overall_summary",
    "summarize_attempts", "DNSTestRequest", "ValidationError", "validate_test_request",
]
