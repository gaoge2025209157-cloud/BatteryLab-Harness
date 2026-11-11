"""Deterministic cyclic-voltammetry feature extraction without fitting."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .analysis_common import contiguous_segments, load_numeric_points, result_envelope, trapezoid

_FIELDS = {
    "potential_V": ("potential_V", "potential", "voltage_V", "voltage", "Ewe_V"),
    "current_A": ("current_A", "current", "i_A"),
}
_UNITS = {"potential_V": "V", "current_A": "A"}


def analyze_cv(
    source: str | Path | Iterable[Mapping[str, Any]],
    *,
    units: Mapping[str, str] | None = None,
    scan_rate: float | None = None,
    scan_rate_unit: str = "V/s",
) -> dict[str, Any]:
    """Analyze CV points with canonical keys ``potential_V`` and ``current_A``.

    A UTF-8 CSV path may be passed instead. Charge is reported only when a
    positive scan rate in V/s is explicitly supplied.
    """
    points = load_numeric_points(
        source, fields=_FIELDS, expected_units=_UNITS, units=units, minimum_points=5
    )
    quality_flags: list[str] = []
    limitations = [
        "Peak values are discrete sampled-point candidates; no baseline subtraction or smoothing is applied.",
        "Peak assignment is based only on scan direction and current extrema, not reaction identity.",
    ]
    if scan_rate is not None:
        try:
            scan_rate = float(scan_rate)
        except (TypeError, ValueError) as error:
            raise ValueError("scan_rate must be a finite positive number.") from error
        if not math.isfinite(scan_rate) or scan_rate <= 0:
            raise ValueError("scan_rate must be a finite positive number.")
        if scan_rate_unit != "V/s":
            raise ValueError("scan_rate_unit must be V/s; implicit conversion is not supported.")
    elif scan_rate_unit != "V/s":
        raise ValueError("scan_rate_unit must be V/s.")

    deltas = [right["potential_V"] - left["potential_V"] for left, right in zip(points, points[1:])]
    nonzero = [delta for delta in deltas if delta != 0]
    if not nonzero:
        raise ValueError("CV potential must change.")
    labels = _direction_labels(deltas)
    if any(delta == 0 for delta in deltas):
        quality_flags.append("repeated_potential_points")

    sweeps: list[dict[str, Any]] = []
    for number, (direction, start_interval, end_interval) in enumerate(contiguous_segments(labels), start=1):
        sweep_points = points[start_interval : end_interval + 2]
        if len(sweep_points) < 3:
            quality_flags.append("short_sweep")
        if direction == "increasing":
            peak_index = max(range(len(sweep_points)), key=lambda index: sweep_points[index]["current_A"])
            peak_type = "oxidation_candidate"
        else:
            peak_index = min(range(len(sweep_points)), key=lambda index: sweep_points[index]["current_A"])
            peak_type = "reduction_candidate"
        if peak_index in (0, len(sweep_points) - 1):
            quality_flags.append("peak_at_sweep_boundary")
        peak = sweep_points[peak_index]
        row: dict[str, Any] = {
            "sweep": number,
            "cycle": (number + 1) // 2,
            "direction": direction,
            "start_index": start_interval,
            "end_index": end_interval + 1,
            "point_count": len(sweep_points),
            "peak_type": peak_type,
            "peak_potential_V": peak["potential_V"],
            "peak_current_A": peak["current_A"],
            "integrated_charge_C": None,
        }
        if scan_rate is not None:
            row["integrated_charge_C"] = sum(
                trapezoid(
                    left["potential_V"],
                    right["potential_V"],
                    left["current_A"],
                    right["current_A"],
                )
                * (1.0 if right["potential_V"] >= left["potential_V"] else -1.0)
                / scan_rate
                for left, right in zip(sweep_points, sweep_points[1:])
            )
        sweeps.append(row)

    cycle_rows = []
    for index in range(0, len(sweeps), 2):
        pair = sweeps[index : index + 2]
        oxidation = next((row for row in pair if row["peak_type"] == "oxidation_candidate"), None)
        reduction = next((row for row in pair if row["peak_type"] == "reduction_candidate"), None)
        separation = None
        if oxidation and reduction:
            separation = abs(oxidation["peak_potential_V"] - reduction["peak_potential_V"])
        cycle_rows.append({
            "cycle": index // 2 + 1,
            "oxidation_peak": _peak_view(oxidation),
            "reduction_peak": _peak_view(reduction),
            "peak_separation_V": separation,
            "complete": oxidation is not None and reduction is not None,
        })
    if len(sweeps) % 2:
        quality_flags.append("incomplete_final_cycle")
    if scan_rate is None:
        limitations.append("Charge is not calculated because scan_rate was not supplied; I·dV is not treated as charge.")

    return result_envelope(
        "direction-segmented sampled extrema with trapezoidal I·dt integration only when scan rate is supplied",
        limitations,
        quality_flags,
        input_schema={"point_keys": _UNITS, "accepted_source": "iterable of mappings or UTF-8 CSV path"},
        scan_rate_V_s=scan_rate,
        point_count=len(points),
        cycle_count=(len(sweeps) + 1) // 2,
        complete_cycle_count=sum(1 for row in cycle_rows if row["complete"]),
        sweeps=sweeps,
        cycles=cycle_rows,
    )


def _direction_labels(deltas: list[float]) -> list[str]:
    labels: list[str | None] = ["increasing" if value > 0 else "decreasing" if value < 0 else None for value in deltas]
    previous = None
    for index, label in enumerate(labels):
        if label is None and previous is not None:
            labels[index] = previous
        elif label is not None:
            previous = label
    following = next(label for label in labels if label is not None)
    for index, label in enumerate(labels):
        if label is None:
            labels[index] = following
    return [str(label) for label in labels]


def _peak_view(row: dict[str, Any] | None) -> dict[str, float] | None:
    if row is None:
        return None
    return {"potential_V": row["peak_potential_V"], "current_A": row["peak_current_A"]}
