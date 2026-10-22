"""Versioned scientific definitions for deterministic cycling metrics.

The manifest is deliberately data-only: it can be hashed into plans, reports and
run records.  Changing any scientific convention requires a new version.
"""

import copy
import hashlib
import json
from typing import Any, Mapping, Optional


SCIENTIFIC_STANDARD_VERSION = "1.0.0"

_STANDARD = {
    "standard_id": "electrochem-harness-galvanostatic-core",
    "version": SCIENTIFIC_STANDARD_VERSION,
    "status": "frozen_pending_domain_review",
    "scope": "galvanostatic cycling exported as current-time-voltage or specific-capacity-voltage text data",
    "conventions": {
        "charge_current_sign": "positive",
        "current_sign_override": "input adapter may invert current only when explicitly configured and audited",
        "capacity_integration": "piecewise-linear trapezoidal integration of current over elapsed time; split intervals at current zero crossings",
        "constant_voltage_stage": "included whenever its measured current and elapsed time are present",
        "specific_capacity_denominator": "active material mass in grams; no specific capacity is calculated when mass is missing",
        "coulombic_efficiency": "discharge_capacity / charge_capacity",
        "retention_reference": "first_complete_discharge_cycle",
        "incomplete_cycle": "retained for quality review but excluded from efficiency, retention and replicate trend claims",
        "average_voltage": "capacity-weighted voltage, equivalently discharge/charge energy divided by corresponding capacity",
        "time_rule": "strictly increasing time is required for current integration; rounded non-increasing time disables reintegration",
        "nonfinite_rule": "NaN and infinity are invalid",
        "outlier_rule": "flag statistically unusual replicate values; never auto-exclude",
    },
    "metrics": {
        "charge_capacity_mAh": {
            "unit": "mAh",
            "formula": "integral(max(I_mA, 0) dt_h)",
            "required_inputs": ["time", "current"],
        },
        "discharge_capacity_mAh": {
            "unit": "mAh",
            "formula": "integral(max(-I_mA, 0) dt_h)",
            "required_inputs": ["time", "current"],
        },
        "specific_capacity_mAh_g": {
            "unit": "mAh g^-1",
            "formula": "capacity_mAh / active_material_mass_g",
            "required_inputs": ["capacity", "active_material_mass"],
        },
        "coulombic_efficiency": {
            "unit": "fraction",
            "formula": "discharge_capacity / charge_capacity",
            "valid_when": "complete cycle and charge_capacity > 0",
        },
        "capacity_retention": {
            "unit": "fraction",
            "formula": "cycle_discharge_capacity / first_complete_cycle_discharge_capacity",
            "valid_when": "reference discharge capacity > 0",
        },
        "average_voltage_V": {
            "unit": "V",
            "formula": "sum(delta_capacity * midpoint_voltage) / sum(delta_capacity)",
            "valid_when": "positive accumulated capacity",
        },
        "dominant_plateau_voltage_V": {
            "unit": "V",
            "formula": "capacity-weighted mean voltage of the fixed voltage bin carrying the largest positive capacity increment",
            "bin_width_V": 0.05,
            "valid_when": "specific-capacity curve contains positive capacity increments",
        },
    },
    "reporting": {
        "minimum_independent_cells_for_repeatability": 3,
        "dispersion": "sample standard deviation (n-1)",
        "confidence_interval": "two-sided 95% Student t interval around the arithmetic mean",
        "show_raw_points": True,
        "single_cell_label": "exploratory",
    },
}


def scientific_standard_manifest() -> dict:
    """Return an independent JSON-compatible copy of the frozen standard."""

    return copy.deepcopy(_STANDARD)


def scientific_standard_hash(manifest: Optional[Mapping[str, Any]] = None) -> str:
    """Return the canonical SHA-256 of a standard manifest."""

    payload = scientific_standard_manifest() if manifest is None else manifest
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scientific_standard_identity() -> dict:
    return {
        "standard_id": _STANDARD["standard_id"],
        "version": SCIENTIFIC_STANDARD_VERSION,
        "sha256": scientific_standard_hash(),
        "status": _STANDARD["status"],
    }
