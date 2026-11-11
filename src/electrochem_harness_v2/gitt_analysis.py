"""Deterministic GITT pulse/rest segmentation and voltage descriptors."""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .analysis_common import contiguous_segments, load_numeric_points, result_envelope

_FIELDS = {
    "time_s": ("time_s", "time"),
    "current_A": ("current_A", "current", "i_A"),
    "voltage_V": ("voltage_V", "voltage", "potential_V", "potential"),
}
_UNITS = {"time_s": "s", "current_A": "A", "voltage_V": "V"}


def analyze_gitt(
    source: str | Path | Iterable[Mapping[str, Any]],
    *,
    current_threshold_A: float,
    units: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Segment GITT data using ``abs(current_A) > current_threshold_A``.

    The interface accepts mappings with ``time_s``, ``current_A``, and
    ``voltage_V`` or a UTF-8 CSV containing those columns.
    """
    try:
        threshold = float(current_threshold_A)
    except (TypeError, ValueError) as error:
        raise ValueError("current_threshold_A must be a finite positive number.") from error
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("current_threshold_A must be a finite positive number.")

    points = load_numeric_points(
        source, fields=_FIELDS, expected_units=_UNITS, units=units, minimum_points=6
    )
    if any(right["time_s"] <= left["time_s"] for left, right in zip(points, points[1:])):
        raise ValueError("GITT time_s values must be strictly increasing.")

    labels = ["pulse" if abs(point["current_A"]) > threshold else "rest" for point in points]
    raw_segments = contiguous_segments(labels)
    if not any(kind == "pulse" for kind, _, _ in raw_segments):
        raise ValueError("No pulse exceeds current_threshold_A.")
    if not any(kind == "rest" for kind, _, _ in raw_segments):
        raise ValueError("No rest interval is at or below current_threshold_A.")

    quality_flags: list[str] = []
    steps: list[dict[str, Any]] = []
    for number, (kind, start, end) in enumerate(raw_segments, start=1):
        segment = points[start : end + 1]
        if len(segment) < 2:
            quality_flags.append("single_point_step")
        steps.append({
            "step": number,
            "kind": kind,
            "start_index": start,
            "end_index": end,
            "start_time_s": segment[0]["time_s"],
            "end_time_s": segment[-1]["time_s"],
            "duration_s": segment[-1]["time_s"] - segment[0]["time_s"],
            "point_count": len(segment),
            "mean_current_A": sum(point["current_A"] for point in segment) / len(segment),
            "start_voltage_V": segment[0]["voltage_V"],
            "end_voltage_V": segment[-1]["voltage_V"],
        })

    pulses: list[dict[str, Any]] = []
    for segment_index, (kind, start, end) in enumerate(raw_segments):
        if kind != "pulse":
            continue
        previous = raw_segments[segment_index - 1] if segment_index > 0 and raw_segments[segment_index - 1][0] == "rest" else None
        following = raw_segments[segment_index + 1] if segment_index + 1 < len(raw_segments) and raw_segments[segment_index + 1][0] == "rest" else None
        baseline = points[previous[2]]["voltage_V"] if previous else None
        instantaneous = points[start]["voltage_V"] - baseline if baseline is not None else None
        steady = points[following[2]]["voltage_V"] - baseline if baseline is not None and following else None
        if previous is None:
            quality_flags.append("pulse_without_preceding_rest")
        if following is None:
            quality_flags.append("pulse_without_following_rest")
        pulses.append({
            "pulse": len(pulses) + 1,
            "step": segment_index + 1,
            "polarity": "positive" if points[start]["current_A"] > 0 else "negative",
            "duration_s": points[end]["time_s"] - points[start]["time_s"],
            "instantaneous_voltage_change_V": instantaneous,
            "pulse_end_voltage_change_V": points[end]["voltage_V"] - baseline if baseline is not None else None,
            "steady_state_voltage_change_V": steady,
            "relaxation_voltage_change_V": points[following[2]]["voltage_V"] - points[end]["voltage_V"] if following else None,
            "diffusion_coefficient_m2_s": None,
        })

    return result_envelope(
        "absolute-current threshold segmentation; voltage differences use the last preceding rest point as baseline",
        [
            "Threshold segmentation depends on the user-supplied current_threshold_A.",
            "Step durations span first to last sampled point and do not infer unsampled transition times.",
            "Diffusion coefficients are not calculated because geometry, composition/thermodynamic response, and other model parameters are not accepted by this deterministic interface.",
        ],
        quality_flags,
        input_schema={"point_keys": _UNITS, "pulse_rule": "abs(current_A) > current_threshold_A"},
        point_count=len(points),
        current_threshold_A=threshold,
        step_count=len(steps),
        pulse_count=len(pulses),
        steps=steps,
        pulses=pulses,
        diffusion_coefficient_m2_s=None,
    )
