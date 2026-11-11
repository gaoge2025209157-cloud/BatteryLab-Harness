"""Deterministic EIS descriptors with no implicit equivalent-circuit fit."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .analysis_common import linear_slope, load_numeric_points, result_envelope

_FIELDS = {
    "frequency_Hz": ("frequency_Hz", "frequency", "freq_Hz", "freq"),
    "z_real_ohm": ("z_real_ohm", "z_real", "zprime_ohm", "zprime", "Z'_ohm"),
    "z_imag_ohm": ("z_imag_ohm", "z_imag", "zdoubleprime_ohm", "zdoubleprime", "Z''_ohm"),
}
_UNITS = {"frequency_Hz": "Hz", "z_real_ohm": "ohm", "z_imag_ohm": "ohm"}


def analyze_eis(
    source: str | Path | Iterable[Mapping[str, Any]],
    *,
    units: Mapping[str, str] | None = None,
    tail_fraction: float = 0.3,
) -> dict[str, Any]:
    """Analyze EIS points and normalize them to descending frequency.

    Input uses signed ``z_imag_ohm``. The returned Nyquist ordinate is
    ``minus_z_imag_ohm = -z_imag_ohm``.
    """
    points = load_numeric_points(
        source, fields=_FIELDS, expected_units=_UNITS, units=units, minimum_points=5
    )
    if not math.isfinite(tail_fraction) or not 0 < tail_fraction <= 0.5:
        raise ValueError("tail_fraction must be finite and in (0, 0.5].")
    if any(point["frequency_Hz"] <= 0 for point in points):
        raise ValueError("All EIS frequencies must be positive.")

    quality_flags: list[str] = []
    frequencies = [point["frequency_Hz"] for point in points]
    if len(set(frequencies)) != len(frequencies):
        quality_flags.append("duplicate_frequencies")
    normalized = sorted(points, key=lambda point: point["frequency_Hz"], reverse=True)
    if frequencies != sorted(frequencies, reverse=True):
        quality_flags.append("frequency_order_normalized")
    for point in normalized:
        point["minus_z_imag_ohm"] = -point["z_imag_ohm"]

    high_count = min(len(normalized), max(3, math.ceil(len(normalized) * 0.2)))
    high_region = normalized[:high_count]
    intercept_point = min(high_region, key=lambda point: abs(point["z_imag_ohm"]))
    peak = max(normalized, key=lambda point: point["minus_z_imag_ohm"])

    tail_count = min(len(normalized), max(3, math.ceil(len(normalized) * tail_fraction)))
    tail = normalized[-tail_count:]
    tail_slope = linear_slope([
        (point["z_real_ohm"], point["minus_z_imag_ohm"]) for point in tail
    ])
    if intercept_point is high_region[-1]:
        quality_flags.append("high_frequency_intercept_at_window_boundary")
    if peak in (normalized[0], normalized[-1]):
        quality_flags.append("minus_z_imag_peak_at_frequency_boundary")

    return result_envelope(
        "descending-frequency normalization, sampled high-frequency intercept candidate, sampled -Z'' maximum, and OLS low-frequency-tail slope",
        [
            "The real-axis intercept is a measured-point candidate, not an extrapolated series resistance.",
            "No equivalent-circuit model is selected or fitted.",
            "The low-frequency slope depends on the requested tail fraction and is not by itself a diffusion coefficient.",
        ],
        quality_flags,
        input_schema={"point_keys": _UNITS, "z_imag_sign": "signed Z'', not -Z''"},
        point_count=len(normalized),
        frequency_range_Hz={"minimum": normalized[-1]["frequency_Hz"], "maximum": normalized[0]["frequency_Hz"]},
        high_frequency_real_axis_intercept_candidate={
            "frequency_Hz": intercept_point["frequency_Hz"],
            "z_real_ohm": intercept_point["z_real_ohm"],
            "z_imag_ohm": intercept_point["z_imag_ohm"],
            "selection": "minimum absolute Z'' among highest-frequency window",
            "window_point_count": high_count,
        },
        minus_z_imag_peak={
            "frequency_Hz": peak["frequency_Hz"],
            "z_real_ohm": peak["z_real_ohm"],
            "minus_z_imag_ohm": peak["minus_z_imag_ohm"],
        },
        low_frequency_tail={
            "point_count": tail_count,
            "frequency_range_Hz": {"minimum": tail[-1]["frequency_Hz"], "maximum": tail[0]["frequency_Hz"]},
            "slope_d_minus_z_imag_d_z_real": tail_slope,
        },
        normalized_points=normalized,
    )
