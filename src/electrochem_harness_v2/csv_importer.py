"""Conservative importer for instrument-exported GCD capacity curves."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import math
from pathlib import Path
import re

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
    """Read GCD exports while preserving instrument values and source rows."""

    _DELIMITERS = (",", "\t", ";", "|")

    def read(
        self,
        path: Path | str,
        conditions: dict | None = None,
        active_material_mass_mg: float | None = None,
    ) -> CsvImportResult:
        """Read and normalize one export.

        ``read(path)`` remains supported.  Normalized point values use seconds,
        volts, amperes and mAh/g.  Bare legacy column names retain their prior
        numeric interpretation but are marked as unit-unverified and are not
        considered reliable enough for current integration.
        """
        source = Path(path)
        digest = self._file_sha256(source)
        encoding = self._detect_encoding(source)
        delimiter, header, header_row = self._locate_header_file(source, encoding)
        mapping = self._mapping(header)
        if not {"time", "capacity", "voltage"}.issubset(mapping):
            raise ValueError("CSV must include time, specific capacity, and voltage columns.")

        units, unit_warnings = self._normalization(header, mapping)
        mass_mg = self._active_material_mass(conditions, active_material_mass_mg)
        points = self._read_points_file(source, encoding, delimiter, header_row, mapping, units)
        if len(points) < 2:
            raise ValueError("CSV contains fewer than two valid data rows.")

        segments, segmentation = self._segments(points, mapping)
        time_reliable = bool(units["time"][2])
        gcd_metrics = analyze_gcd_metrics(
            tuple(points),
            segments,
            active_material_mass_mg=mass_mg,
            time_reliable=time_reliable,
        )
        repeated = sum(1 for left, right in zip(points, points[1:]) if right["time"] <= left["time"])
        warnings = list(unit_warnings)
        warnings.extend(segmentation["warnings"])
        if "current" not in mapping:
            warnings.append("No current column was identified; current integration was not performed.")
        elif mass_mg is None:
            warnings.append("Active-material mass is missing; current integration was not performed.")
        if repeated:
            warnings.append(
                "{} repeated or reversed time interval(s) were found; affected segments are not integrated.".format(repeated)
            )
        warnings.extend(gcd_metrics.get("warnings") or [])
        warnings = list(dict.fromkeys(warnings))

        negative = sum(1 for point in points if point["voltage"] < 0)
        labels = {name: header[index] for name, index in mapping.items()}
        unit_report = {
            name: {
                "source_header": header[mapping[name]],
                "normalized_unit": units[name][1],
                "conversion_factor": units[name][0],
                "explicit": units[name][2],
            }
            for name in ("time", "voltage", "capacity", "current")
            if name in mapping
        }
        limitations = [
            "Specific capacity is instrument-exported and its mass basis is unverified.",
            "Instrument-exported capacity is preserved; integrated capacity is reported separately when eligible.",
            "Segment directions are auditable candidates requiring researcher review.",
        ]
        if "current" not in mapping:
            limitations.insert(1, "No current integration is performed when no current column is present.")
        return CsvImportResult(
            metadata=CsvImportMetadata(digest, source.name, encoding, delimiter, "specific_capacity_curve", labels),
            points=tuple(points),
            analysis={
                "row_count": len(points),
                "voltage_range_V": [min(item["voltage"] for item in points), max(item["voltage"] for item in points)],
                "negative_voltage_count": negative,
                "repeated_or_reversed_time_pairs": repeated,
                "active_material_mass_mg": mass_mg,
                "unit_normalization": unit_report,
                "segmentation_method": segmentation["method"],
                "segmentation_confidence": segmentation["confidence"],
                "confidence": segmentation["confidence"],
                "warnings": warnings,
                "segments": gcd_metrics["segments"],
                "cycles": gcd_metrics["cycles"],
                "gcd_summary": gcd_metrics["summary"],
                "limitations": limitations,
            },
        )

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _detect_encoding(path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), ""):
                        if not chunk:
                            break
                return encoding
            except UnicodeDecodeError:
                continue
        raise ValueError("Unable to decode CSV as UTF-8 or GB18030.")

    @classmethod
    def _locate_header_file(cls, path: Path, encoding: str) -> tuple[str, list[str], int]:
        parts: list[str] = []
        size = 0
        with path.open("r", encoding=encoding, newline="") as handle:
            for _ in range(100):
                line = handle.readline()
                if not line:
                    break
                remaining = 65536 - size
                if remaining <= 0:
                    break
                parts.append(line[:remaining])
                size += len(parts[-1])
        return cls._locate_header("".join(parts))

    @staticmethod
    def _decode(raw: bytes) -> tuple[str, str]:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return raw.decode(encoding), encoding
            except UnicodeDecodeError:
                continue
        raise ValueError("Unable to decode CSV as UTF-8 or GB18030.")

    @classmethod
    def _locate_header(cls, text: str) -> tuple[str, list[str], int]:
        """Find a real table header after optional notes and blank lines."""
        best: tuple[int, int, str, list[str], int] | None = None
        sample = text[:65536]
        for delimiter in cls._DELIMITERS:
            reader = csv.reader(io.StringIO(sample), delimiter=delimiter)
            for _ in range(100):
                try:
                    row = next(reader)
                except StopIteration:
                    break
                if not row or not any(cell.strip() for cell in row):
                    continue
                mapping = cls._mapping(row)
                required = len({"time", "capacity", "voltage"}.intersection(mapping))
                score = required * 10 + len(mapping)
                candidate = (score, len(row), delimiter, row, reader.line_num)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
                if required == 3:
                    break
        if best is None or best[0] < 30:
            raise ValueError("Unable to identify a supported CSV header and delimiter.")
        return best[2], best[3], best[4]

    @classmethod
    def _rows(cls, text: str) -> tuple[str, list[list[str]]]:
        """Compatibility helper retained for callers of the earlier private API."""
        delimiter, header, header_row = cls._locate_header(text)
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [row for row in reader if reader.line_num >= header_row]
        if rows:
            rows[0] = header
        return delimiter, rows

    @staticmethod
    def _compact_header(raw_name: str) -> str:
        return re.sub(r"[\s_]+", "", str(raw_name).strip().lower()).replace("µ", "u").replace("μ", "u")

    @classmethod
    def _mapping(cls, header: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for index, raw_name in enumerate(header):
            name = cls._compact_header(raw_name)
            if "specificcapacity" in name or "比容量" in name or name.startswith("capacity"):
                mapping.setdefault("capacity", index)
            elif "time" in name or "时间" in name:
                mapping.setdefault("time", index)
            elif "voltage" in name or "电压" in name or name.startswith("ewe"):
                mapping.setdefault("voltage", index)
            elif "current" in name or "电流" in name or re.match(r"^i(?:[/\[(]|$)", name):
                mapping.setdefault("current", index)
            elif "cycle" in name or "循环" in name:
                mapping.setdefault("cycle", index)
            elif "step" in name or "工步" in name or "步骤" in name:
                mapping.setdefault("step", index)
            elif any(token in name for token in ("direction", "status", "state", "mode", "状态", "充放电")):
                mapping.setdefault("direction", index)
            elif "soc" in name or "dod" in name:
                mapping.setdefault("auxiliary", index)
        return mapping

    @classmethod
    def _normalization(
        cls, header: list[str], mapping: dict[str, int]
    ) -> tuple[dict[str, tuple[float, str, bool]], list[str]]:
        units: dict[str, tuple[float, str, bool]] = {}
        warnings: list[str] = []
        for role in ("time", "voltage", "capacity", "current"):
            if role not in mapping:
                continue
            raw = header[mapping[role]]
            unit = cls._unit_for(role, raw)
            units[role] = unit
            if not unit[2]:
                warnings.append(
                    "Column {!r} has no explicit unit; legacy numeric interpretation as {} is retained but unit-unverified.".format(
                        raw, unit[1]
                    )
                )
        return units, warnings

    @classmethod
    def _unit_for(cls, role: str, raw_header: str) -> tuple[float, str, bool]:
        name = cls._compact_header(raw_header).replace("·", "").replace("−", "-")
        if role == "time":
            if "minute" in name or "分钟" in name or "min" in name:
                return 60.0, "s", True
            if "hour" in name or "小时" in name or re.search(r"(?:/|\(|\[)h(?:\)|\])?$", name):
                return 3600.0, "s", True
            if "second" in name or "秒" in name or "sec" in name or re.search(r"(?:/|\(|\[)s(?:\)|\])?$", name):
                return 1.0, "s", True
            if name in {"time", "testtime", "时间", "测试时间"}:
                return 1.0, "s", False
        elif role == "voltage":
            if "mv" in name:
                return 0.001, "V", True
            if re.search(r"(?:voltage|电压|ewe)(?:/|\(|\[)?v(?:\)|\])?$", name):
                return 1.0, "V", True
            if name in {"voltage", "电压", "ewe"}:
                return 1.0, "V", False
        elif role == "current":
            if "ma" in name:
                return 0.001, "A", True
            if "ua" in name:
                return 0.000001, "A", True
            if re.search(r"(?:current|电流|i)(?:/|\(|\[)?a(?:\)|\])?$", name):
                return 1.0, "A", True
            if name in {"current", "电流", "i"}:
                return 1.0, "A", False
        elif role == "capacity":
            if "mah/g" in name or "mahg-1" in name or "mahg^-1" in name:
                return 1.0, "mAh/g", True
            if "ah/g" in name or "ahg-1" in name or "ahg^-1" in name:
                return 1000.0, "mAh/g", True
            if name in {"capacity", "specificcapacity", "比容量"}:
                return 1.0, "mAh/g", False
        raise ValueError("Unsupported or ambiguous unit in column header {!r}.".format(raw_header))

    @staticmethod
    def _active_material_mass(conditions: dict | None, explicit_mass: float | None) -> float | None:
        if conditions is not None and not isinstance(conditions, dict):
            raise TypeError("conditions must be a mapping when provided.")
        value = explicit_mass
        if value is None and conditions is not None:
            value = conditions.get("active_material_mass_mg")
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("Active-material mass must be a positive finite number in mg.")
        try:
            mass = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Active-material mass must be a positive finite number in mg.") from error
        if not math.isfinite(mass) or mass <= 0:
            raise ValueError("Active-material mass must be a positive finite number in mg.")
        return mass

    @classmethod
    def _read_points(
        cls,
        text: str,
        delimiter: str,
        header_row: int,
        mapping: dict[str, int],
        units: dict[str, tuple[float, str, bool]],
    ) -> list[dict]:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        return cls._read_points_from_reader(reader, header_row, mapping, units)

    @classmethod
    def _read_points_file(
        cls,
        path: Path,
        encoding: str,
        delimiter: str,
        header_row: int,
        mapping: dict[str, int],
        units: dict[str, tuple[float, str, bool]],
    ) -> list[dict]:
        with path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            return cls._read_points_from_reader(reader, header_row, mapping, units)

    @classmethod
    def _read_points_from_reader(
        cls,
        reader,
        header_row: int,
        mapping: dict[str, int],
        units: dict[str, tuple[float, str, bool]],
    ) -> list[dict]:
        points: list[dict] = []
        for row in reader:
            line_number = reader.line_num
            if line_number <= header_row or not row or not any(cell.strip() for cell in row):
                continue
            values: dict[str, float] = {}
            try:
                for role in ("time", "capacity", "voltage", "current"):
                    if role not in mapping:
                        continue
                    value = float(row[mapping[role]].strip()) * units[role][0]
                    if not math.isfinite(value):
                        raise ValueError("non-finite")
                    values[role] = value
            except (IndexError, ValueError) as error:
                message = "Non-finite" if str(error) == "non-finite" else "Invalid"
                raise ValueError("{} numeric data at source row {}.".format(message, line_number)) from error
            point = {
                "source_row": line_number,
                "time": values["time"],
                "capacity": values["capacity"],
                "voltage": values["voltage"],
            }
            if "current" in values:
                point["current"] = values["current"]
            for role in ("cycle", "step", "direction"):
                if role in mapping:
                    point[role] = row[mapping[role]].strip() if len(row) > mapping[role] else ""
            if "auxiliary" in mapping:
                point["auxiliary"] = row[mapping["auxiliary"]] if len(row) > mapping["auxiliary"] else ""
            points.append(point)
        return points

    @staticmethod
    def _direction_value(value: object) -> str | None:
        text = str(value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")
        if not text:
            return None
        if "discharge" in text or "dchg" in text or "放电" in text:
            return "discharge"
        if "charge" in text or "chg" in text or "充电" in text:
            return "charge"
        return None

    @staticmethod
    def _current_sign(point: dict) -> int:
        current = point.get("current")
        if current is None or current == 0:
            return 0
        return 1 if current > 0 else -1

    @classmethod
    def _segments(cls, points: list[dict], mapping: dict[str, int] | None = None) -> tuple[list[dict], dict]:
        mapping = mapping or {}
        boundaries: dict[int, set[str]] = {0: {"start"}, len(points): {"end"}}
        warnings: list[str] = []
        recognized_directions = [cls._direction_value(point.get("direction")) for point in points]
        has_cycle_or_step = any(
            role in mapping and any(str(point.get(role, "")).strip() for point in points)
            for role in ("cycle", "step")
        )
        has_explicit = has_cycle_or_step or any(recognized_directions)
        has_current_sign = any(cls._current_sign(point) for point in points)

        for index, (left, right) in enumerate(zip(points, points[1:]), start=1):
            explicit_change = False
            for role in ("cycle", "step"):
                if role in mapping and str(left.get(role, "")).strip() != str(right.get(role, "")).strip():
                    boundaries.setdefault(index, set()).add(role)
                    explicit_change = True
            left_direction = cls._direction_value(left.get("direction"))
            right_direction = cls._direction_value(right.get("direction"))
            if left_direction and right_direction and left_direction != right_direction:
                boundaries.setdefault(index, set()).add("direction")
                explicit_change = True
            left_sign, right_sign = cls._current_sign(left), cls._current_sign(right)
            if left_sign and right_sign and left_sign != right_sign and not explicit_change:
                boundaries.setdefault(index, set()).add("current_sign")
            if left["capacity"] > 1.0 and right["capacity"] <= max(0.05, left["capacity"] * 0.1):
                boundaries.setdefault(index, set()).add("capacity_reset")

        previous_nonzero_sign = 0
        for index, point in enumerate(points):
            sign = cls._current_sign(point)
            if not sign:
                continue
            if previous_nonzero_sign and sign != previous_nonzero_sign:
                boundaries.setdefault(index, set()).add("current_sign")
            previous_nonzero_sign = sign

        if has_explicit:
            method, confidence = "explicit_cycle_step_direction", "high"
        elif has_current_sign:
            method, confidence = "current_sign", "medium"
        elif any("capacity_reset" in methods for methods in boundaries.values()):
            method, confidence = "capacity_reset", "medium"
        else:
            method, confidence = "voltage_direction", "low"
            previous_sign = 0
            for index, (left, right) in enumerate(zip(points, points[1:]), start=1):
                delta = right["voltage"] - left["voltage"]
                sign = 1 if delta > 0 else -1 if delta < 0 else previous_sign
                if previous_sign and sign and sign != previous_sign:
                    boundaries.setdefault(index, set()).add("voltage_turn")
                previous_sign = sign
            warnings.append("No explicit step/direction, usable current sign, or capacity reset was found; voltage direction fallback is low confidence.")

        if has_current_sign:
            warnings.append(
                "Current-sign direction inference uses the candidate convention positive current = charge and negative current = discharge; the instrument convention is not validated."
            )

        ordered = sorted(boundaries)
        result: list[dict] = []
        for number, (start, end) in enumerate(zip(ordered, ordered[1:]), start=1):
            segment = points[start:end]
            if not segment:
                continue
            explicit = {value for value in (cls._direction_value(item.get("direction")) for item in segment) if value}
            signs = {cls._current_sign(item) for item in segment if cls._current_sign(item)}
            delta_v = segment[-1]["voltage"] - segment[0]["voltage"]
            opening = boundaries[start]
            closing = boundaries[end]
            boundary_evidence = opening.union(closing)
            segment_warnings: list[str] = []
            explicit_current_conflict = False
            current_sign_convention = None
            if len(explicit) == 1:
                direction = next(iter(explicit))
                segment_method = "explicit_direction"
                segment_confidence = "high"
                expected_sign = 1 if direction == "charge" else -1
                if signs and signs != {expected_sign}:
                    explicit_current_conflict = True
                    segment_confidence = "medium"
                    segment_warnings.append(
                        "Explicit direction conflicts with one or more current signs; explicit direction was retained, but automatic Origin eligibility was disabled."
                    )
            elif len(explicit) > 1:
                direction = "unknown"
                segment_method = "conflicting_explicit_direction"
                segment_confidence = "low"
                segment_warnings.append("Conflicting explicit direction/status values occur in this segment.")
            elif len(signs) == 1:
                direction = "charge" if next(iter(signs)) > 0 else "discharge"
                segment_method = "current_sign"
                segment_confidence = "medium"
                current_sign_convention = "candidate_positive_charge_negative_discharge"
                segment_warnings.append(
                    "Direction was inferred using the candidate convention positive current = charge and negative current = discharge; verify the instrument convention."
                )
            elif len(signs) > 1:
                direction = "unknown"
                segment_method = "mixed_current_sign"
                segment_confidence = "low"
                segment_warnings.append("Mixed current signs remain inside this segment.")
            else:
                direction = "charge" if delta_v > 0 else "discharge" if delta_v < 0 else "unknown"
                if "capacity_reset" in boundary_evidence:
                    segment_method = "capacity_reset_with_voltage_direction"
                    segment_confidence = "medium"
                elif boundary_evidence.intersection({"cycle", "step", "direction"}):
                    segment_method = "explicit_boundary_with_voltage_direction"
                    segment_confidence = "medium"
                else:
                    segment_method = "voltage_direction"
                    segment_confidence = "low"
            cycle_values = [str(item.get("cycle", "")).strip() for item in segment if str(item.get("cycle", "")).strip()]
            exported_capacity = max(item["capacity"] for item in segment)
            result.append({
                "segment_id": "segment-{}".format(number),
                "start_source_row": segment[0]["source_row"],
                "end_source_row": segment[-1]["source_row"],
                "specific_capacity_mAh_g": exported_capacity,
                "instrument_exported_specific_capacity_mAh_g": exported_capacity,
                "direction_candidate": direction,
                "direction_inference_method": segment_method,
                "current_sign_convention": current_sign_convention,
                "explicit_current_conflict": explicit_current_conflict,
                "cycle_candidate": cycle_values[0] if cycle_values and len(set(cycle_values)) == 1 else None,
                "closed_by_capacity_reset": "capacity_reset" in closing,
                "closed_by_explicit_boundary": bool(closing.intersection({"cycle", "step", "direction"})),
                "closed_by_current_sign": "current_sign" in closing,
                "segmentation_method": segment_method,
                "confidence": segment_confidence,
                "warnings": segment_warnings,
                "origin_eligible": (
                    direction in {"charge", "discharge"}
                    and segment_confidence in {"high", "medium"}
                    and not explicit_current_conflict
                ),
                "review_status": "candidate_requires_researcher_review",
            })
        if "direction" in mapping and not any(recognized_directions):
            warnings.append("A direction/status column was found, but none of its values were recognized.")
        if not [index for index in boundaries if index not in (0, len(points))] and len(result) == 1:
            warnings.append("No internal segment boundary was detected.")
        return result, {"method": method, "confidence": confidence, "warnings": warnings}
