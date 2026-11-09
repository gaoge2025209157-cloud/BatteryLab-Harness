"""Conservative importer for instrument-exported capacity curves."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

from .gcd_metrics import analyze_gcd_metrics


@dataclass(frozen=True)
class CsvImportMetadata:
    sha256: str
    source_name: str
    encoding: str
    delimiter: str
    mode: str
    column_mapping: dict[str, str]


@dataclass(frozen=True)
class CsvImportResult:
    metadata: CsvImportMetadata
    analysis: dict
    points: tuple[dict, ...]


class GcdCsvImporter:
    """Read capacity-export data without mistaking SOC/DOD for current."""

    def read(self, path: Path | str) -> CsvImportResult:
        source = Path(path)
        raw = source.read_bytes()
        text, encoding = self._decode(raw)
        delimiter, rows = self._rows(text)
        if len(rows) < 2:
            raise ValueError("CSV contains no data rows.")
        header = rows[0]
        mapping = self._mapping(header)
        if not {"time", "capacity", "voltage"}.issubset(mapping):
            raise ValueError("CSV must include time, specific capacity, and voltage columns.")
        points: list[dict] = []
        for line_number, row in enumerate(rows[1:], start=2):
            if not row or not any(cell.strip() for cell in row):
                continue
            try:
                time_value = float(row[mapping["time"]])
                capacity = float(row[mapping["capacity"]])
                voltage = float(row[mapping["voltage"]])
            except (IndexError, ValueError) as error:
                raise ValueError("Invalid numeric data at source row {}.".format(line_number)) from error
            if not all(math.isfinite(value) for value in (time_value, capacity, voltage)):
                raise ValueError("Non-finite numeric data at source row {}.".format(line_number))
            point = {"source_row": line_number, "time": time_value, "capacity": capacity, "voltage": voltage}
            if "auxiliary" in mapping:
                point["auxiliary"] = row[mapping["auxiliary"]] if len(row) > mapping["auxiliary"] else ""
            points.append(point)
        if len(points) < 2:
            raise ValueError("CSV contains fewer than two valid data rows.")
        segments = self._segments(points)
        gcd_metrics = analyze_gcd_metrics(tuple(points), segments)
        repeated = sum(1 for left, right in zip(points, points[1:]) if right["time"] <= left["time"])
        negative = sum(1 for point in points if point["voltage"] < 0)
        digest = hashlib.sha256(raw).hexdigest()
        labels = {name: header[index] for name, index in mapping.items()}
        return CsvImportResult(
            metadata=CsvImportMetadata(digest, source.name, encoding, delimiter, "specific_capacity_curve", labels),
            points=tuple(points),
            analysis={
                "row_count": len(points),
                "voltage_range_V": [min(item["voltage"] for item in points), max(item["voltage"] for item in points)],
                "negative_voltage_count": negative,
                "repeated_or_reversed_time_pairs": repeated,
                "segments": gcd_metrics["segments"],
                "cycles": gcd_metrics["cycles"],
                "gcd_summary": gcd_metrics["summary"],
                "limitations": [
                    "Specific capacity is instrument-exported and its mass basis is unverified.",
                    "No current integration is performed when no current column is present.",
                    "Segment directions are candidates requiring researcher review.",
                ],
            },
        )

    @staticmethod
    def _decode(raw: bytes) -> tuple[str, str]:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise ValueError("Unable to decode CSV as UTF-8 or GB18030.")

    @staticmethod
    def _rows(text: str) -> tuple[str, list[list[str]]]:
        for delimiter in (",", "\t", ";"):
            rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
            if rows and len(rows[0]) >= 3:
                return delimiter, rows
        raise ValueError("Unable to identify a supported CSV delimiter.")

    @staticmethod
    def _mapping(header: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for index, raw_name in enumerate(header):
            name = "".join(str(raw_name).strip().lower().split())
            if "时间" in name or "time" in name:
                mapping.setdefault("time", index)
            elif "比容量" in name or "specificcapacity" in name or name == "capacity":
                mapping.setdefault("capacity", index)
            elif "电压" in name or "voltage" in name:
                mapping.setdefault("voltage", index)
            elif "soc" in name or "dod" in name:
                mapping.setdefault("auxiliary", index)
            elif "电流" in name or "current" in name:
                mapping.setdefault("current", index)
        return mapping

    @staticmethod
    def _segments(points: list[dict]) -> list[dict]:
        boundaries = [0]
        for index, (left, right) in enumerate(zip(points, points[1:]), start=1):
            if left["capacity"] > 1.0 and right["capacity"] <= max(0.05, left["capacity"] * 0.1):
                boundaries.append(index)
        boundaries.append(len(points))
        result: list[dict] = []
        for number, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
            segment = points[start:end]
            delta_v = segment[-1]["voltage"] - segment[0]["voltage"]
            direction = "charge" if delta_v > 0.2 else "discharge" if delta_v < -0.2 else "unknown"
            result.append({
                "segment_id": "segment-{}".format(number),
                "start_source_row": segment[0]["source_row"],
                "end_source_row": segment[-1]["source_row"],
                "specific_capacity_mAh_g": max(item["capacity"] for item in segment),
                "direction_candidate": direction,
                "closed_by_capacity_reset": end < len(points),
            })
        return result
