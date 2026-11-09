"""Fail-closed comparison of experimental metrics against reviewed claims."""
from __future__ import annotations

import math
from typing import Any, Mapping

from .models import ComparisonOutcome, KnowledgeClaim


_UNIT_ALIASES = {"mah/g": "mah/g", "mahg-1": "mah/g", "mAh/g": "mah/g", "s/cm": "s/cm", "scm-1": "s/cm"}


def _unit(value: str | None) -> str:
    compact = "".join(str(value or "").lower().replace("−", "-").split())
    return _UNIT_ALIASES.get(compact, compact)


def _same(left: Any, right: Any) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=1e-8, abs_tol=1e-12)
    except (TypeError, ValueError):
        return str(left).strip().casefold() == str(right).strip().casefold()


def compare_metric(
    *,
    observed_value: float,
    observed_unit: str,
    observed_conditions: Mapping[str, Any],
    claim: KnowledgeClaim,
) -> ComparisonOutcome:
    if claim.status != "approved":
        return ComparisonOutcome(claim.claim_id, "not_approved", None, None, ("Literature claim requires researcher approval.",))
    if claim.value is None or not claim.metric_id:
        return ComparisonOutcome(claim.claim_id, "insufficient_data", None, None, ("Claim has no executable numeric metric.",))
    if not math.isfinite(float(observed_value)) or not math.isfinite(float(claim.value)):
        return ComparisonOutcome(claim.claim_id, "insufficient_data", None, None, ("Numeric values must be finite.",))
    if _unit(observed_unit) != _unit(claim.unit):
        return ComparisonOutcome(claim.claim_id, "not_comparable", None, None, ("Metric units do not match.",))
    missing = [key for key in claim.conditions if observed_conditions.get(key) in (None, "")]
    if missing:
        return ComparisonOutcome(claim.claim_id, "insufficient_context", None, None, ("Missing conditions: {}".format(", ".join(missing)),))
    mismatched = [key for key, expected in claim.conditions.items() if not _same(expected, observed_conditions[key])]
    if mismatched:
        return ComparisonOutcome(claim.claim_id, "not_comparable", None, None, ("Mismatched conditions: {}".format(", ".join(mismatched)),))
    difference = float(observed_value) - float(claim.value)
    decision = "above_reference" if difference > 0 else "below_reference" if difference < 0 else "matches_reference"
    return ComparisonOutcome(claim.claim_id, "comparable", decision, difference, ("Approved evidence and declared conditions match.",))
