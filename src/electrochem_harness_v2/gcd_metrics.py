"""Deterministic GCD metrics derived from normalized instrument exports."""
from __future__ import annotations

import math


def _finite_float(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("{} must be numeric.".format(label)) from error
    if not math.isfinite(number):
        raise ValueError("{} must be finite.".format(label))
    return number


def _segment_points(points, segment):
    start = int(segment["start_source_row"])
    end = int(segment["end_source_row"])
    return [item for item in points if start <= int(item["source_row"]) <= end]


def capacity_weighted_voltage(points) -> float | None:
    """Integrate V dQ / integral dQ using only positive capacity increments."""
    weighted = 0.0
    capacity = 0.0
    for left, right in zip(points, points[1:]):
        left_capacity = _finite_float(left["capacity"], "capacity")
        right_capacity = _finite_float(right["capacity"], "capacity")
        left_voltage = _finite_float(left["voltage"], "voltage")
        right_voltage = _finite_float(right["voltage"], "voltage")
        delta_q = right_capacity - left_capacity
        if delta_q <= 0:
            continue
        weighted += (left_voltage + right_voltage) * 0.5 * delta_q
        capacity += delta_q
        if not math.isfinite(weighted) or not math.isfinite(capacity):
            raise ValueError("Capacity-weighted voltage accumulation must remain finite.")
    result = weighted / capacity if capacity > 0 else None
    if result is not None and not math.isfinite(result):
        raise ValueError("Capacity-weighted voltage must be finite.")
    return result


def integrate_specific_capacity(points, active_material_mass_mg: float | None, time_reliable: bool) -> tuple[float | None, str]:
    """Trapezoidally integrate current without substituting for exported capacity."""
    if active_material_mass_mg is None:
        return None, "missing_active_material_mass"
    mass_mg = _finite_float(active_material_mass_mg, "active_material_mass_mg")
    if mass_mg <= 0:
        raise ValueError("active_material_mass_mg must be positive.")
    if not time_reliable:
        return None, "unverified_time_unit"
    if len(points) < 2:
        return None, "fewer_than_two_points"
    if any("current" not in item for item in points):
        return None, "missing_current"

    integral_a_s = 0.0
    for left, right in zip(points, points[1:]):
        left_time = _finite_float(left["time"], "time")
        right_time = _finite_float(right["time"], "time")
        delta_time = right_time - left_time
        if delta_time <= 0:
            return None, "non_increasing_time"
        left_current = _finite_float(left["current"], "current")
        right_current = _finite_float(right["current"], "current")
        integral_a_s += (left_current + right_current) * 0.5 * delta_time
        if not math.isfinite(integral_a_s):
            raise ValueError("Current integration must remain finite.")
    mass_g = mass_mg / 1000.0
    result = abs(integral_a_s) / (3.6 * mass_g)
    if not math.isfinite(result):
        raise ValueError("Integrated specific capacity must be finite.")
    return result, "integrated"


def segment_is_closed(segment: dict) -> bool:
    """Return whether any accepted segmentation rule closes the segment."""
    return bool(
        segment.get("closed_by_capacity_reset")
        or segment.get("closed_by_explicit_boundary")
        or segment.get("closed_by_current_sign")
    )


def analyze_gcd_metrics(
    points,
    segments,
    active_material_mass_mg: float | None = None,
    time_reliable: bool = False,
) -> dict:
    """Enrich candidate segments and pair sequential charge/discharge candidates."""
    enriched = []
    warnings: list[str] = []
    for segment in segments:
        row = dict(segment)
        segment_points = _segment_points(points, segment)
        row["capacity_weighted_average_voltage_V"] = capacity_weighted_voltage(segment_points)
        integrated, status = integrate_specific_capacity(segment_points, active_material_mass_mg, time_reliable)
        exported = _finite_float(row["specific_capacity_mAh_g"], "specific_capacity_mAh_g")
        row["instrument_exported_specific_capacity_mAh_g"] = exported
        row["integrated_specific_capacity_mAh_g"] = integrated
        row["integrated_capacity_mAh_g"] = integrated
        row["integration_status"] = status
        difference = _finite_float(integrated - exported, "integration difference") if integrated is not None else None
        difference_percent = (
            _finite_float(difference / exported * 100.0, "integration difference percent")
            if difference is not None and exported > 0
            else None
        )
        row["integration_difference_mAh_g"] = difference
        row["capacity_difference_mAh_g"] = difference
        row["integration_difference_percent"] = difference_percent
        if status == "non_increasing_time":
            warning = "{} contains repeated or reversed time and was not integrated.".format(row["segment_id"])
            row.setdefault("warnings", []).append(warning)
            warnings.append(warning)
        enriched.append(row)

    cycles = []
    cursor = 0
    if enriched and enriched[0]["direction_candidate"] == "discharge":
        cursor = 1
    while cursor < len(enriched):
        charge = enriched[cursor]
        if charge["direction_candidate"] != "charge":
            cursor += 1
            continue
        discharge_index = cursor + 1
        discharge = enriched[discharge_index] if discharge_index < len(enriched) else None
        if not discharge or discharge["direction_candidate"] != "discharge":
            cursor += 1
            continue
        charge_capacity = _finite_float(charge["specific_capacity_mAh_g"], "charge capacity")
        discharge_capacity = _finite_float(discharge["specific_capacity_mAh_g"], "discharge capacity")
        charge_voltage = charge["capacity_weighted_average_voltage_V"]
        discharge_voltage = discharge["capacity_weighted_average_voltage_V"]
        complete = bool(segment_is_closed(charge) and segment_is_closed(discharge))
        cycles.append({
            "cycle": len(cycles) + 1,
            "cycle_candidate": charge.get("cycle_candidate") or discharge.get("cycle_candidate"),
            "charge_specific_capacity_mAh_g": charge_capacity,
            "discharge_specific_capacity_mAh_g": discharge_capacity,
            "charge_integrated_specific_capacity_mAh_g": charge.get("integrated_specific_capacity_mAh_g"),
            "discharge_integrated_specific_capacity_mAh_g": discharge.get("integrated_specific_capacity_mAh_g"),
            "charge_integration_difference_mAh_g": charge.get("integration_difference_mAh_g"),
            "discharge_integration_difference_mAh_g": discharge.get("integration_difference_mAh_g"),
            "average_charge_voltage_V": charge_voltage,
            "average_discharge_voltage_V": discharge_voltage,
            "polarization_voltage_V": (
                charge_voltage - discharge_voltage
                if charge_voltage is not None and discharge_voltage is not None
                else None
            ),
            "coulombic_efficiency_percent": (
                discharge_capacity / charge_capacity * 100 if complete and charge_capacity > 0 else None
            ),
            "capacity_retention_percent": None,
            "complete": complete,
            "charge_segment_id": charge["segment_id"],
            "discharge_segment_id": discharge["segment_id"],
        })
        cursor = discharge_index + 1

    reference = next((item["discharge_specific_capacity_mAh_g"] for item in cycles if item["complete"]), None)
    if reference and reference > 0:
        for item in cycles:
            if item["complete"]:
                item["capacity_retention_percent"] = item["discharge_specific_capacity_mAh_g"] / reference * 100
    complete_cycles = [item for item in cycles if item["complete"]]
    maximum_cycle = max(complete_cycles, key=lambda item: item["discharge_specific_capacity_mAh_g"], default=None)
    integrated_segments = [item for item in enriched if item["integration_status"] == "integrated"]
    integration_attempted_segments = [
        item for item in enriched if item["integration_status"] in {"integrated", "non_increasing_time"}
    ]
    summary = {
        "complete_cycle_count": len(complete_cycles),
        "first_complete_discharge_capacity_mAh_g": complete_cycles[0]["discharge_specific_capacity_mAh_g"] if complete_cycles else None,
        "maximum_complete_discharge_capacity_mAh_g": maximum_cycle["discharge_specific_capacity_mAh_g"] if maximum_cycle else None,
        "maximum_complete_discharge_cycle": maximum_cycle["cycle"] if maximum_cycle else None,
        "latest_complete_discharge_capacity_mAh_g": complete_cycles[-1]["discharge_specific_capacity_mAh_g"] if complete_cycles else None,
        "latest_capacity_retention_percent": complete_cycles[-1]["capacity_retention_percent"] if complete_cycles else None,
        "latest_coulombic_efficiency_percent": complete_cycles[-1]["coulombic_efficiency_percent"] if complete_cycles else None,
        "first_complete_average_discharge_voltage_V": complete_cycles[0]["average_discharge_voltage_V"] if complete_cycles else None,
        "latest_average_discharge_voltage_V": complete_cycles[-1]["average_discharge_voltage_V"] if complete_cycles else None,
        "latest_polarization_voltage_V": complete_cycles[-1]["polarization_voltage_V"] if complete_cycles else None,
        "integrated_segment_count": len(integrated_segments),
        "integration_eligible_segment_count": len(integrated_segments),
        "integration_attempted_segment_count": len(integration_attempted_segments),
        "total_segment_count": len(enriched),
        "scientific_boundary": "循环方向和分段仍需研究人员结合仪器步骤审核；积分容量独立报告，不替代仪器导出比容量。",
    }
    return {"segments": enriched, "cycles": cycles, "summary": summary, "warnings": warnings}


def build_codex_feature_packet(analysis_payload: dict) -> dict:
    """Return a bounded feature-only packet. Raw rows and point-level data never cross this boundary."""
    metadata = dict(analysis_payload.get("metadata") or {})
    analysis = dict(analysis_payload.get("analysis") or analysis_payload)
    summary = dict(analysis.get("gcd_summary") or {})
    cycles = []
    for row in analysis.get("cycles") or []:
        cycles.append({
            "cycle": row.get("cycle"),
            "charge_specific_capacity_mAh_g": row.get("charge_specific_capacity_mAh_g"),
            "discharge_specific_capacity_mAh_g": row.get("discharge_specific_capacity_mAh_g"),
            "charge_integrated_specific_capacity_mAh_g": row.get("charge_integrated_specific_capacity_mAh_g"),
            "discharge_integrated_specific_capacity_mAh_g": row.get("discharge_integrated_specific_capacity_mAh_g"),
            "average_charge_voltage_V": row.get("average_charge_voltage_V"),
            "average_discharge_voltage_V": row.get("average_discharge_voltage_V"),
            "polarization_voltage_V": row.get("polarization_voltage_V"),
            "coulombic_efficiency_percent": row.get("coulombic_efficiency_percent"),
            "capacity_retention_percent": row.get("capacity_retention_percent"),
            "complete": row.get("complete"),
        })
    segments = []
    for row in analysis.get("segments") or []:
        segments.append({
            "segment_id": row.get("segment_id"),
            "direction_candidate": row.get("direction_candidate"),
            "specific_capacity_mAh_g": row.get("specific_capacity_mAh_g"),
            "instrument_exported_specific_capacity_mAh_g": row.get("instrument_exported_specific_capacity_mAh_g"),
            "integrated_specific_capacity_mAh_g": row.get("integrated_specific_capacity_mAh_g"),
            "integration_difference_mAh_g": row.get("integration_difference_mAh_g"),
            "capacity_weighted_average_voltage_V": row.get("capacity_weighted_average_voltage_V"),
            "closed_by_capacity_reset": row.get("closed_by_capacity_reset"),
            "segmentation_method": row.get("segmentation_method"),
            "confidence": row.get("confidence"),
            "warnings": list(row.get("warnings") or []),
        })
    return {
        "source_sha256": metadata.get("sha256"),
        "source_name": metadata.get("source_name"),
        "mode": metadata.get("mode"),
        "column_mapping": dict(metadata.get("column_mapping") or {}),
        "row_count": analysis.get("row_count"),
        "voltage_range_V": analysis.get("voltage_range_V"),
        "negative_voltage_count": analysis.get("negative_voltage_count"),
        "repeated_or_reversed_time_pairs": analysis.get("repeated_or_reversed_time_pairs"),
        "active_material_mass_mg": analysis.get("active_material_mass_mg"),
        "unit_normalization": dict(analysis.get("unit_normalization") or {}),
        "segmentation_method": analysis.get("segmentation_method"),
        "segmentation_confidence": analysis.get("segmentation_confidence"),
        "confidence": analysis.get("confidence", analysis.get("segmentation_confidence")),
        "warnings": list(analysis.get("warnings") or []),
        "complete_cycles": cycles,
        "candidate_segments": segments,
        "gcd_summary": summary,
        "limitations": list(analysis.get("limitations") or []),
        "feature_boundary": "Only deterministic aggregate features and auditable quality flags are supplied; point-level input is excluded.",
    }
