import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .models import CycleMetrics, CyclingPoint


REQUIRED_COLUMNS = {"cycle", "time_s", "current_mA", "voltage_V"}


def load_cycling_csv(path: Path) -> List[CyclingPoint]:
    source = Path(path)
    with source.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        available = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - available)
        if missing:
            raise ValueError("Missing required columns: " + ", ".join(missing))

        points = []
        for source_row, row in enumerate(reader, start=2):
            try:
                cycle_value = float(row["cycle"])
                cycle = int(cycle_value)
                values = (
                    float(row["time_s"]),
                    float(row["current_mA"]),
                    float(row["voltage_V"]),
                )
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid numeric value at source row {}".format(source_row)) from error
            if cycle <= 0 or cycle_value != cycle:
                raise ValueError("cycle must be a positive integer at source row {}".format(source_row))
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Non-finite value at source row {}".format(source_row))
            points.append(
                CyclingPoint(
                    cycle=cycle,
                    time_s=values[0],
                    current_mA=values[1],
                    voltage_V=values[2],
                    source_row=source_row,
                )
            )
    if not points:
        raise ValueError("CSV contains no data rows")
    return points


def _integrate_linear_segment(
    start: CyclingPoint, end: CyclingPoint
) -> Tuple[float, float, float, float]:
    """Return charge/discharge capacity (mAh) and energy (mWh).

    Current and voltage are treated as linear within an interval. A current
    sign crossing is split at zero so charge and discharge cannot cancel.
    """
    duration = end.time_s - start.time_s
    if duration <= 0:
        raise ValueError("time_s must increase strictly")

    knots = [(0.0, start.current_mA, start.voltage_V)]
    if start.current_mA * end.current_mA < 0:
        fraction = abs(start.current_mA) / (abs(start.current_mA) + abs(end.current_mA))
        crossing_voltage = start.voltage_V + fraction * (end.voltage_V - start.voltage_V)
        knots.append((fraction, 0.0, crossing_voltage))
    knots.append((1.0, end.current_mA, end.voltage_V))

    charge_capacity = discharge_capacity = 0.0
    charge_energy = discharge_energy = 0.0
    for left, right in zip(knots, knots[1:]):
        left_fraction, left_current, left_voltage = left
        right_fraction, right_current, right_voltage = right
        dt_hours = duration * (right_fraction - left_fraction) / 3600.0
        average_current = (left_current + right_current) / 2.0
        average_power = (
            left_voltage * left_current + right_voltage * right_current
        ) / 2.0
        if average_current >= 0:
            charge_capacity += average_current * dt_hours
            charge_energy += max(average_power, 0.0) * dt_hours
        else:
            discharge_capacity += -average_current * dt_hours
            discharge_energy += -min(average_power, 0.0) * dt_hours
    return charge_capacity, discharge_capacity, charge_energy, discharge_energy


def _safe_ratio(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator > 0 else None


def analyze_cycles(
    points: Iterable[CyclingPoint], active_mass_mg: Optional[float] = None
) -> List[CycleMetrics]:
    if active_mass_mg is not None and active_mass_mg <= 0:
        raise ValueError("active_mass_mg must be greater than zero")

    grouped: Dict[int, List[CyclingPoint]] = defaultdict(list)
    for point in points:
        grouped[point.cycle].append(point)

    raw = []
    for cycle in sorted(grouped):
        cycle_points = grouped[cycle]
        charge_capacity = discharge_capacity = 0.0
        charge_energy = discharge_energy = 0.0
        for start, end in zip(cycle_points, cycle_points[1:]):
            values = _integrate_linear_segment(start, end)
            charge_capacity += values[0]
            discharge_capacity += values[1]
            charge_energy += values[2]
            discharge_energy += values[3]
        raw.append((cycle, charge_capacity, discharge_capacity, charge_energy, discharge_energy))

    reference_discharge = next((item[2] for item in raw if item[2] > 0), 0.0)
    mass_g = active_mass_mg / 1000.0 if active_mass_mg is not None else None
    metrics = []
    for cycle, charge_capacity, discharge_capacity, charge_energy, discharge_energy in raw:
        average_charge = _safe_ratio(charge_energy, charge_capacity)
        average_discharge = _safe_ratio(discharge_energy, discharge_capacity)
        voltage_gap = (
            average_charge - average_discharge
            if average_charge is not None and average_discharge is not None
            else None
        )
        metrics.append(
            CycleMetrics(
                cycle=cycle,
                charge_capacity_mAh=charge_capacity,
                discharge_capacity_mAh=discharge_capacity,
                charge_energy_mWh=charge_energy,
                discharge_energy_mWh=discharge_energy,
                specific_charge_capacity_mAh_g=(charge_capacity / mass_g if mass_g else None),
                specific_discharge_capacity_mAh_g=(discharge_capacity / mass_g if mass_g else None),
                coulombic_efficiency=_safe_ratio(discharge_capacity, charge_capacity),
                capacity_retention=_safe_ratio(discharge_capacity, reference_discharge),
                average_charge_voltage_V=average_charge,
                average_discharge_voltage_V=average_discharge,
                voltage_gap_V=voltage_gap,
            )
        )
    return metrics
