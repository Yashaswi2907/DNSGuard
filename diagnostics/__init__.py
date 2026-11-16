"""Rule-based DNS diagnostic engine."""
from .diagnostic_engine import (
    DISCLAIMER, RULES, diagnose_attempt, diagnose_resolver, diagnose_test, outcome_label,
)

__all__ = ["DISCLAIMER", "RULES", "diagnose_attempt", "diagnose_resolver", "diagnose_test",
           "outcome_label"]
