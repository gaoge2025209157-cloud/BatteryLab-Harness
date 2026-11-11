"""Shared validation and CSV loading for deterministic analyses."""
from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


def load_numeric_points(
    source: str | Path | Iterable[Mapping[str, Any]],
    *,
    fields: Mapping[str, tuple[str, ...]],
    expected_units: Mapping[str, str],
    units: Mapping[str, str] | None = None,
    minimum_points: int,
) -> list[dict[str, float]]:
    """Load finite numeric points from mappings or a CSV path.

    ``fields`` maps each canonical output key to accepted input column names.
    Units are global and must exactly match ``expected_units``; conversion and
    mixed per-row units are deliberately unsupported.
    """
    supplied_units = dict(expected_units if units is None else units)
    if set(supplied_units) != set(expected_units):
        raise ValueError("Units must be supplied for exactly: {}.".format(", ".join(expected_units)))
    for field, expected in expected_units.items():
        if supplied_units[field] != expected:
            raise ValueError("Unsupported or mixed unit for {}: expected {}.".format(field, expected))

    rows = _read_rows(source)
    if len(rows) < minimum_points:
        raise ValueError("At least {} points are required.".format(minimum_points))
    result: list[dict[str, float]] = []
    for index, row in enumerate(rows, start=1):
        normalized = {_normalize_name(key): value for key, value in row.items()}
        point: dict[str, float] = {}
        for canonical, aliases in fields.items():
            value = _find_value(normalized, aliases)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError("Missing {} at data row {}.".format(canonical, index))
            try:
                number = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid {} at data row {}.".format(canonical, index)) from error
            if not math.isfinite(number):
                raise ValueError("Non-finite {} at data row {}.".format(canonical, index))
            point[canonical] = number
        _validate_row_units(row, expected_units, index)
        result.append(point)
    return result


def result_envelope(method: str, limitations: list[str], quality_flags: list[str], **values: Any) -> dict[str, Any]:
    """Build the stable top-level schema shared by all analysis modules."""
    return {
        "schema_version": SCHEMA_VERSION,
        "method": method,
        **values,
        "limitations": limitations,
        "quality_flags": sorted(set(quality_flags)),
    }


def trapezoid(x0: float, x1: float, y0: float, y1: float) -> float:
    return (x1 - x0) * (y0 + y1) * 0.5


def linear_slope(points: list[tuple[float, float]]) -> float:
    """Return an ordinary least-squares slope, rejecting degenerate x data."""
    x_mean = sum(point[0] for point in points) / len(points)
    y_mean = sum(point[1] for point in points) / len(points)
    denominator = sum((point[0] - x_mean) ** 2 for point in points)
    if denominator == 0:
        raise ValueError("Cannot calculate a slope when all x values are equal.")
    return sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator


def contiguous_segments(labels: list[str]) -> list[tuple[str, int, int]]:
    if not labels:
        return []
    segments: list[tuple[str, int, int]] = []
    start = 0
    for index in range(1, len(labels)):
        if labels[index] != labels[start]:
            segments.append((labels[start], start, index - 1))
            start = index
    segments.append((labels[start], start, len(labels) - 1))
    return segments


def _read_rows(source: str | Path | Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV must contain a header row.")
            return [dict(row) for row in reader if any(str(value).strip() for value in row.values())]
    if isinstance(source, Mapping):
        raise TypeError("Points must be an iterable of mappings, not one mapping.")
    rows = list(source)
    if not all(isinstance(row, Mapping) for row in rows):
        raise TypeError("Every point must be a mapping.")
    return rows


def _normalize_name(name: object) -> str:
    text = str(name).lower().replace("″", "doubleprime").replace("''", "doubleprime")
    text = text.replace("′", "prime").replace("'", "prime")
    return "".join(character for character in text if character.isalnum())


def _find_value(row: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        key = _normalize_name(alias)
        if key in row:
            return row[key]
    return None


def _validate_row_units(row: Mapping[str, Any], expected_units: Mapping[str, str], index: int) -> None:
    nested = row.get("units")
    if nested is not None and not isinstance(nested, Mapping):
        raise ValueError("units at data row {} must be a mapping.".format(index))
    for field, expected in expected_units.items():
        candidates = []
        if isinstance(nested, Mapping) and field in nested:
            candidates.append(nested[field])
        for key in (field + "_unit", field.rsplit("_", 1)[0] + "_unit"):
            if key in row:
                candidates.append(row[key])
        if any(value != expected for value in candidates):
            raise ValueError("Mixed or unsupported unit for {} at data row {}.".format(field, index))
