"""Analysis for LAND exports that already contain specific capacity.

These files have no current or cycle column. Results therefore use the exported
specific capacity directly and conservatively reconstruct cycles at capacity
reset boundaries; no current integration is attempted.
"""

import csv
from pathlib import Path
from typing import List, Tuple


def _decode(path: Path) -> Tuple[str, str]:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode capacity-curve export")


def _normalized(value: str) -> str:
    return "".join(character for character in value.strip().lower() if character.isalnum())


def _find_table(text: str):
    for delimiter in (",", "\t", ";"):
        rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
        for header_index, header in enumerate(rows[:50]):
            normalized = [_normalized(item) for item in header]
            mapping = {}
            for index, value in enumerate(normalized):
                if "时间" in value or "time" in value:
                    mapping.setdefault("time", index)
                if "比容量" in value or "specificcapacity" in value:
                    mapping.setdefault("capacity", index)
                if "电压" in value or "voltage" in value:
                    mapping.setdefault("voltage", index)
            if len(mapping) == 3:
                return delimiter, rows, header_index, mapping
    raise ValueError("Not a LAND time/specific-capacity/voltage curve export")


def _time_factor_to_hours(header: str) -> float:
    value = _normalized(header)
    if "min" in value or "分钟" in value:
        return 1.0 / 60.0
    if value.endswith("s") or "sec" in value or "秒" in value:
        return 1.0 / 3600.0
    return 1.0


def _segment_direction(segment: List[Tuple[float, float, float]]) -> str:
    delta = segment[-1][2] - segment[0][2]
    if delta > 0.2:
        return "charge"
    if delta < -0.2:
        return "discharge"
    return "unknown"


def analyze_land_capacity_curve(path: Path) -> dict:
    source = Path(path)
    text, encoding = _decode(source)
    delimiter, rows, header_index, mapping = _find_table(text)
    header = rows[header_index]
    time_factor = _time_factor_to_hours(header[mapping["time"]])
    points = []
    for source_row, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        try:
            points.append(
                (
                    float(row[mapping["time"]]) * time_factor,
                    float(row[mapping["capacity"]]),
                    float(row[mapping["voltage"]]),
                )
            )
        except (IndexError, ValueError) as error:
            raise ValueError("Invalid capacity-curve value at source row {}".format(source_row)) from error
    if len(points) < 2:
        raise ValueError("Capacity-curve export contains fewer than two data rows")

    segments = []
    start = 0
    reset_count = 0
    for index, (left, right) in enumerate(zip(points, points[1:])):
        if left[1] > 1.0 and right[1] <= max(0.05, left[1] * 0.1):
            segments.append((points[start : index + 1], True))
            start = index + 1
            reset_count += 1
    segments.append((points[start:], False))

    segment_summaries = []
    for number, (segment, closed_by_reset) in enumerate(segments, start=1):
        voltage_metrics = _voltage_metrics(segment)
        segment_summaries.append(
            {
                "segment": number,
                "direction": _segment_direction(segment),
                "start_time_h": segment[0][0],
                "end_time_h": segment[-1][0],
                "start_voltage_V": segment[0][2],
                "end_voltage_V": segment[-1][2],
                "specific_capacity_mAh_g": max(item[1] for item in segment),
                "closed_by_capacity_reset": closed_by_reset,
                **voltage_metrics,
            }
        )

    initial_discharge = None
    cursor = 0
    if segment_summaries and segment_summaries[0]["direction"] == "discharge":
        initial_discharge = segment_summaries[0]["specific_capacity_mAh_g"]
        cursor = 1

    cycles = []
    while cursor < len(segment_summaries):
        charge = segment_summaries[cursor]
        if charge["direction"] != "charge":
            cursor += 1
            continue
        discharge = segment_summaries[cursor + 1] if cursor + 1 < len(segment_summaries) else None
        if discharge is None or discharge["direction"] != "discharge":
            break
        charge_capacity = charge["specific_capacity_mAh_g"]
        discharge_capacity = discharge["specific_capacity_mAh_g"]
        complete = bool(charge["closed_by_capacity_reset"] and discharge["closed_by_capacity_reset"])
        cycles.append(
            {
                "cycle": len(cycles) + 1,
                "charge_specific_capacity_mAh_g": charge_capacity,
                "discharge_specific_capacity_mAh_g": discharge_capacity,
                "coulombic_efficiency": discharge_capacity / charge_capacity if complete and charge_capacity > 0 else None,
                "capacity_retention": None,
                "average_charge_voltage_V": charge["average_voltage_V"],
                "average_discharge_voltage_V": discharge["average_voltage_V"],
                "charge_plateau_voltage_V": charge["dominant_plateau_voltage_V"],
                "discharge_plateau_voltage_V": discharge["dominant_plateau_voltage_V"],
                "charge_plateau_capacity_fraction": charge["dominant_plateau_capacity_fraction"],
                "discharge_plateau_capacity_fraction": discharge["dominant_plateau_capacity_fraction"],
                "complete": complete,
                "charge_segment": charge["segment"],
                "discharge_segment": discharge["segment"],
            }
        )
        cursor += 2

    reference = next(
        (item["discharge_specific_capacity_mAh_g"] for item in cycles if item["complete"]),
        None,
    )
    if reference:
        for item in cycles:
            if item["complete"]:
                item["capacity_retention"] = item["discharge_specific_capacity_mAh_g"] / reference

    repeated_times = sum(1 for left, right in zip(points, points[1:]) if right[0] <= left[0])
    negative_voltages = sum(1 for item in points if item[2] < 0)
    issues = []
    if repeated_times:
        issues.append(
            {
                "code": "repeated_rounded_time",
                "message": "{} adjacent time values are repeated/non-increasing because the export time is rounded; current integration is disabled.".format(repeated_times),
                "blocking": False,
            }
        )
    if negative_voltages:
        issues.append(
            {
                "code": "negative_voltage",
                "message": "{} points have voltage below 0 V; verify whether this is an intended cutoff/overshoot or an instrument/data issue.".format(negative_voltages),
                "blocking": False,
            }
        )
    if cycles and not cycles[-1]["complete"]:
        issues.append(
            {
                "code": "incomplete_final_cycle",
                "message": "The final discharge segment has no following capacity reset; its efficiency and retention are not calculated.",
                "blocking": False,
            }
        )

    completed = [item for item in cycles if item["complete"]]
    conclusions = [
        "读取 {} 个数据点，测试时间范围为 {:.6g} h。".format(len(points), max(item[0] for item in points)),
        "识别 {} 个容量段、{} 个完整充放电循环。".format(len(segments), len(completed)),
    ]
    if completed:
        conclusions.append(
            "完整循环放电比容量由 {:.6g} 降至 {:.6g} mAh/g，保持率为 {:.2%}。".format(
                completed[0]["discharge_specific_capacity_mAh_g"],
                completed[-1]["discharge_specific_capacity_mAh_g"],
                completed[-1]["capacity_retention"],
            )
        )

    return {
        "import_metadata": {
            "mode": "specific_capacity_curve",
            "cycle_mapping_convention": "initial_discharge_unpaired_then_charge_discharge_pairs",
            "cycle_number_basis": "reconstructed_complete_pair_index",
            "normalization_basis": "source_exported_specific_capacity_denominator_unverified",
            "encoding": encoding,
            "delimiter": "tab" if delimiter == "\t" else delimiter,
            "header_row": header_index + 1,
            "detected_columns": {
                "time": header[mapping["time"]],
                "specific_capacity": header[mapping["capacity"]],
                "voltage": header[mapping["voltage"]],
            },
            "capacity_reset_count": reset_count,
        },
        "report": {
            "status": "warning" if issues else "ok",
            "source_rows": len(points),
            "duration_h": max(item[0] for item in points) - min(item[0] for item in points),
            "voltage_range_V": [min(item[2] for item in points), max(item[2] for item in points)],
            "initial_discharge_capacity_mAh_g": initial_discharge,
            "segments": segment_summaries,
            "cycles": cycles,
            "quality_issues": issues,
            "conclusions": conclusions,
            "limitations": [
                "The export has no current column, so capacity/energy are not reintegrated.",
                "Cycle boundaries are reconstructed from exported specific-capacity resets.",
                "The initial discharge is retained as an unpaired segment; reconstructed cycle 1 begins with the next charge/discharge pair.",
                "Specific-capacity normalization cannot be audited without active-mass metadata.",
            ],
        },
    }



def _voltage_metrics(
    segment: List[Tuple[float, float, float]], bin_width_V: float = 0.05
) -> dict:
    """Return capacity-weighted mean voltage and the dominant dQ voltage bin."""
    total_capacity = 0.0
    weighted_voltage = 0.0
    bins = {}
    for left, right in zip(segment, segment[1:]):
        delta_capacity = right[1] - left[1]
        if delta_capacity <= 0:
            continue
        midpoint_voltage = (left[2] + right[2]) / 2.0
        total_capacity += delta_capacity
        weighted_voltage += midpoint_voltage * delta_capacity
        bin_index = round(midpoint_voltage / bin_width_V)
        bucket = bins.setdefault(bin_index, [0.0, 0.0])
        bucket[0] += delta_capacity
        bucket[1] += midpoint_voltage * delta_capacity
    if total_capacity <= 0 or not bins:
        return {
            "average_voltage_V": None,
            "dominant_plateau_voltage_V": None,
            "dominant_plateau_capacity_fraction": None,
            "plateau_bin_width_V": bin_width_V,
        }
    dominant_capacity, dominant_weighted_voltage = max(
        bins.values(), key=lambda bucket: bucket[0]
    )
    return {
        "average_voltage_V": weighted_voltage / total_capacity,
        "dominant_plateau_voltage_V": dominant_weighted_voltage / dominant_capacity,
        "dominant_plateau_capacity_fraction": dominant_capacity / total_capacity,
        "plateau_bin_width_V": bin_width_V,
    }
