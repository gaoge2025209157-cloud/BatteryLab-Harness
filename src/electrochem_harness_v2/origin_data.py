"""Prepare the exact table contract consumed by the legacy Origin plotting engine."""
from __future__ import annotations

import csv
from pathlib import Path

from .csv_importer import CsvImportResult
from .gcd_metrics import segment_is_closed


def prepare_origin_tables(imported: CsvImportResult, target: Path | str, maximum_cycles: int = 8) -> dict[str, Path]:
    """Create legacy-compatible charge/discharge and cycling tables without changing raw data."""
    output = Path(target)
    output.mkdir(parents=True, exist_ok=True)
    segments = _origin_candidate_segments(list(imported.analysis["segments"]))
    cycles, labels = _reconstruct_cycles(segments)
    selected_cycles = _representative_cycles([item for item in cycles if item["complete"]], maximum_cycles)
    curves_path = output / "origin_curves.csv"
    initial_path = output / "origin_initial_discharge.csv"
    summary_path = output / "origin_cycle_summary.csv"
    segment_by_row = _segment_lookup(segments)
    with curves_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["cycle", "direction", "specific_capacity_mAh_g", "voltage_V"])
        writer.writeheader()
        for point in imported.points:
            segment_index = segment_by_row.get(point["source_row"])
            if segment_index is None or segment_index not in labels:
                continue
            cycle, direction = labels[segment_index]
            if cycle not in selected_cycles:
                continue
            writer.writerow({
                "cycle": cycle,
                "direction": direction,
                "specific_capacity_mAh_g": point["capacity"],
                "voltage_V": point["voltage"],
            })
    with initial_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["cycle", "direction", "specific_capacity_mAh_g", "voltage_V"])
        writer.writeheader()
        for point in imported.points:
            segment_index = segment_by_row.get(point["source_row"])
            if segment_index is None or segment_index not in labels:
                continue
            cycle, direction = labels[segment_index]
            if cycle != 0:
                continue
            writer.writerow({
                "cycle": 0,
                "direction": direction,
                "specific_capacity_mAh_g": point["capacity"],
                "voltage_V": point["voltage"],
            })
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["cycle", "charge_specific_capacity_mAh_g", "discharge_specific_capacity_mAh_g", "coulombic_efficiency_percent", "complete"])
        writer.writeheader()
        for cycle in cycles:
            writer.writerow({
                "cycle": cycle["cycle"],
                "charge_specific_capacity_mAh_g": cycle["charge_specific_capacity_mAh_g"],
                "discharge_specific_capacity_mAh_g": cycle["discharge_specific_capacity_mAh_g"],
                "coulombic_efficiency_percent": cycle["coulombic_efficiency_percent"],
                "complete": str(cycle["complete"]).lower(),
            })
    return {"curves": curves_path, "summary": summary_path, "initial_discharge": initial_path}


def _origin_candidate_segments(segments: list[dict]) -> list[dict]:
    """Use only auditable charge/discharge candidates; never substitute integrated values."""
    result = []
    for source_index, segment in enumerate(segments):
        direction = segment.get("direction_candidate")
        confidence = segment.get("confidence")
        review_status = segment.get("review_status")
        if review_status == "rejected":
            continue
        reviewed = review_status in {"reviewed", "approved"} and direction in {"charge", "discharge"}
        eligible = segment.get("origin_eligible")
        if reviewed:
            eligible = True
        elif eligible is None:
            eligible = direction in {"charge", "discharge"} and confidence in {None, "high", "medium"}
        if not eligible or direction not in {"charge", "discharge"}:
            continue
        candidate = dict(segment)
        candidate["_source_segment_index"] = source_index
        result.append(candidate)
    return result


def _reconstruct_cycles(segments: list[dict]) -> tuple[list[dict], dict[int, tuple[int, str]]]:
    labels: dict[int, tuple[int, str]] = {}
    cycles: list[dict] = []
    cursor = 0
    if segments and segments[0]["direction_candidate"] == "discharge":
        labels[0] = (0, "discharge")
        cursor = 1
    cycle_number = 1
    while cursor < len(segments):
        charge = segments[cursor]
        if charge["direction_candidate"] != "charge":
            labels[cursor] = (cycle_number, charge["direction_candidate"])
            cursor += 1
            cycle_number += 1
            continue
        labels[cursor] = (cycle_number, "charge")
        discharge_index = cursor + 1
        discharge = segments[discharge_index] if discharge_index < len(segments) else None
        source_index = int(charge.get("_source_segment_index", cursor))
        discharge_source_index = (
            int(discharge.get("_source_segment_index", discharge_index)) if discharge is not None else None
        )
        if (
            discharge is None
            or discharge["direction_candidate"] != "discharge"
            or discharge_source_index != source_index + 1
        ):
            cycles.append({
                "cycle": cycle_number,
                "charge_specific_capacity_mAh_g": charge["specific_capacity_mAh_g"],
                "discharge_specific_capacity_mAh_g": "",
                "coulombic_efficiency_percent": "",
                "complete": False,
            })
            cursor += 1
            cycle_number += 1
            continue
        labels[discharge_index] = (cycle_number, "discharge")
        complete = bool(segment_is_closed(charge) and segment_is_closed(discharge))
        charge_capacity = charge["specific_capacity_mAh_g"]
        discharge_capacity = discharge["specific_capacity_mAh_g"]
        cycles.append({
            "cycle": cycle_number,
            "charge_specific_capacity_mAh_g": charge_capacity,
            "discharge_specific_capacity_mAh_g": discharge_capacity,
            "coulombic_efficiency_percent": discharge_capacity / charge_capacity * 100 if complete and charge_capacity > 0 else "",
            "complete": complete,
        })
        cursor += 2
        cycle_number += 1
    return cycles, labels


def _segment_lookup(segments: list[dict]) -> dict[int, int]:
    result: dict[int, int] = {}
    for index, segment in enumerate(segments):
        for row in range(segment["start_source_row"], segment["end_source_row"] + 1):
            result[row] = index
    return result


def _representative_cycles(cycles: list[dict], limit: int) -> set[int]:
    numbers = [item["cycle"] for item in cycles]
    if len(numbers) <= limit:
        return set(numbers)
    selected = {numbers[0], numbers[-1]}
    for item in range(1, limit - 1):
        selected.add(numbers[round(item * (len(numbers) - 1) / (limit - 1))])
    return selected
