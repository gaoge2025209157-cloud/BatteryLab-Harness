"""Deterministic descriptive statistics for same-metric replicates."""
from __future__ import annotations

import csv
import math
import statistics
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .analysis_common import result_envelope


def summarize_replicates(
    source: str | Path | Iterable[Mapping[str, Any]],
    *,
    metric: str | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    """Summarize rows containing ``value``, ``metric``, and ``unit``.

    ``metric`` and ``unit`` may instead be supplied once as keyword arguments.
    Every row that also declares either field must agree exactly.
    """
    rows = _read_rows(source)
    if len(rows) < 2:
        raise ValueError("At least two replicate values are required.")
    values: list[float] = []
    metrics: set[str] = set()
    units: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if "value" not in row or str(row["value"]).strip() == "":
            raise ValueError("Missing value at data row {}.".format(index))
        try:
            value = float(row["value"])
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid value at data row {}.".format(index)) from error
        if not math.isfinite(value):
            raise ValueError("Non-finite value at data row {}.".format(index))
        values.append(value)
        row_metric = str(row.get("metric") or metric or "").strip()
        row_unit = str(row.get("unit") or unit or "").strip()
        if not row_metric:
            raise ValueError("metric is required globally or on every row.")
        if not row_unit:
            raise ValueError("unit is required globally or on every row.")
        metrics.add(row_metric)
        units.add(row_unit)
    if metric is not None:
        metrics.add(str(metric).strip())
    if unit is not None:
        units.add(str(unit).strip())
    if len(metrics) != 1:
        raise ValueError("Replicates mix different metrics.")
    if len(units) != 1:
        raise ValueError("Replicates mix different units; implicit conversion is not supported.")

    n = len(values)
    mean = statistics.fmean(values)
    sample_standard_deviation = statistics.stdev(values)
    quality_flags: list[str] = []
    coefficient_of_variation = None
    if mean == 0:
        quality_flags.append("coefficient_of_variation_undefined_zero_mean")
    else:
        coefficient_of_variation = sample_standard_deviation / abs(mean) * 100
    if n < 3:
        quality_flags.append("insufficient_replicates_n_lt_3")

    return result_envelope(
        "unweighted descriptive statistics; sample standard deviation uses the n-1 denominator",
        [
            "These are descriptive statistics for one metric and one unit only.",
            "No significance test, outlier removal, confidence interval, or automatic inferential conclusion is performed.",
            "n < 3 is explicitly insufficient for replicate-level interpretation.",
        ],
        quality_flags,
        input_schema={"row_keys": {"value": "finite number", "metric": "string", "unit": "string"}},
        metric=next(iter(metrics)),
        unit=next(iter(units)),
        n=n,
        mean=mean,
        sample_standard_deviation=sample_standard_deviation,
        coefficient_of_variation_percent=coefficient_of_variation,
        minimum=min(values),
        maximum=max(values),
        replicate_sufficiency="insufficient_n_lt_3" if n < 3 else "descriptive_only",
        inferential_statistics_performed=False,
        significance_conclusion=None,
    )


def analyze_replicates(
    source: str | Path | Iterable[Mapping[str, Any]],
    *,
    metric: str | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    """Alias for :func:`summarize_replicates`."""
    return summarize_replicates(source, metric=metric, unit=unit)


def _read_rows(source: str | Path | Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if isinstance(source, (str, Path)):
        with Path(source).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError("CSV must contain a header row.")
            return [dict(row) for row in reader if any(str(value).strip() for value in row.values())]
    if isinstance(source, Mapping):
        raise TypeError("Replicates must be an iterable of mappings, not one mapping.")
    rows = list(source)
    if not all(isinstance(row, Mapping) for row in rows):
        raise TypeError("Every replicate must be a mapping.")
    return rows
