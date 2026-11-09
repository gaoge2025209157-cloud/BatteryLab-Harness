"""Deterministic GCD metrics derived from instrument-exported capacity curves."""
from __future__ import annotations


def _segment_points(points, segment):
    start = int(segment["start_source_row"])
    end = int(segment["end_source_row"])
    return [item for item in points if start <= int(item["source_row"]) <= end]


def capacity_weighted_voltage(points) -> float | None:
    """Integrate V dQ / integral dQ using only positive capacity increments."""
    weighted = 0.0
    capacity = 0.0
    for left, right in zip(points, points[1:]):
        delta_q = float(right["capacity"]) - float(left["capacity"])
        if delta_q <= 0:
            continue
        weighted += (float(left["voltage"]) + float(right["voltage"])) * 0.5 * delta_q
        capacity += delta_q
    return weighted / capacity if capacity > 0 else None


def analyze_gcd_metrics(points, segments) -> dict:
    enriched = []
    for segment in segments:
        row = dict(segment)
        row["capacity_weighted_average_voltage_V"] = capacity_weighted_voltage(_segment_points(points, segment))
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
        discharge = enriched[cursor + 1] if cursor + 1 < len(enriched) else None
        if not discharge or discharge["direction_candidate"] != "discharge":
            break
        charge_capacity = float(charge["specific_capacity_mAh_g"])
        discharge_capacity = float(discharge["specific_capacity_mAh_g"])
        charge_voltage = charge["capacity_weighted_average_voltage_V"]
        discharge_voltage = discharge["capacity_weighted_average_voltage_V"]
        complete = bool(charge["closed_by_capacity_reset"] and discharge["closed_by_capacity_reset"])
        cycles.append({
            "cycle": len(cycles) + 1,
            "charge_specific_capacity_mAh_g": charge_capacity,
            "discharge_specific_capacity_mAh_g": discharge_capacity,
            "average_charge_voltage_V": charge_voltage,
            "average_discharge_voltage_V": discharge_voltage,
            "polarization_voltage_V": (charge_voltage - discharge_voltage) if charge_voltage is not None and discharge_voltage is not None else None,
            "coulombic_efficiency_percent": discharge_capacity / charge_capacity * 100 if complete and charge_capacity > 0 else None,
            "capacity_retention_percent": None,
            "complete": complete,
            "charge_segment_id": charge["segment_id"],
            "discharge_segment_id": discharge["segment_id"],
        })
        cursor += 2
    reference = next((item["discharge_specific_capacity_mAh_g"] for item in cycles if item["complete"]), None)
    if reference and reference > 0:
        for item in cycles:
            if item["complete"]:
                item["capacity_retention_percent"] = item["discharge_specific_capacity_mAh_g"] / reference * 100
    complete_cycles = [item for item in cycles if item["complete"]]
    maximum_cycle = max(complete_cycles, key=lambda item: item["discharge_specific_capacity_mAh_g"], default=None)
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
        "scientific_boundary": "循环方向和容量重置仍需结合仪器步骤审核；比容量质量口径未确认时仅视为仪器导出值。",
    }
    return {"segments": enriched, "cycles": cycles, "summary": summary}


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
            "capacity_weighted_average_voltage_V": row.get("capacity_weighted_average_voltage_V"),
            "closed_by_capacity_reset": row.get("closed_by_capacity_reset"),
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
        "complete_cycles": cycles,
        "candidate_segments": segments,
        "gcd_summary": summary,
        "limitations": list(analysis.get("limitations") or []),
        "feature_boundary": "Only deterministic aggregate features and auditable quality flags are supplied; point-level input is excluded.",
    }
