"""LAND battery tester text-export adapter.

The public LAND native binary format is not documented. This module therefore
reads auditable CSV/TXT exports and refuses Excel/binary files rather than
silently guessing their layout.
"""

import csv
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import CyclingPoint


ALIASES = {
    "cycle": {
        "cycle", "cycleid", "cycleno", "cyclenumber", "循环", "循环号", "循环序号",
        "循环编号", "圈数", "周次",
    },
    "time": {
        "time", "times", "testtime", "totaltime", "totaltimes", "totaltimesec",
        "recordtime", "elapsedtime", "测试时间", "总时间", "总时间s", "累计时间",
        "累计时间s", "记录时间", "时间s", "时间",
    },
    "current": {
        "current", "currenta", "currentma", "currentua", "curr", "cur",
        "电流", "电流a", "电流ma", "电流ua",
    },
    "voltage": {
        "voltage", "voltagev", "voltagemv", "volt", "vol", "电压", "电压v", "电压mv",
    },
}


def _normalize(value: str) -> str:
    value = value.strip().lower().replace("μ", "u").replace("µ", "u")
    return "".join(character for character in value if character.isalnum())


@dataclass(frozen=True)
class LandImportConfig:
    charge_current_sign: str = "positive"
    current_unit: str = "auto"
    voltage_unit: str = "auto"
    time_unit: str = "auto"
    column_map: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.charge_current_sign not in {"positive", "negative"}:
            raise ValueError("charge_current_sign must be 'positive' or 'negative'")
        if self.current_unit not in {"auto", "A", "mA", "uA"}:
            raise ValueError("current_unit must be auto, A, mA, or uA")
        if self.voltage_unit not in {"auto", "V", "mV"}:
            raise ValueError("voltage_unit must be auto, V, or mV")
        if self.time_unit not in {"auto", "s", "min", "h"}:
            raise ValueError("time_unit must be auto, s, min, or h")


@dataclass(frozen=True)
class LandImportResult:
    points: List[CyclingPoint]
    detected_columns: Dict[str, str]
    detected_units: Dict[str, str]
    delimiter: str
    encoding: str
    header_row: int
    charge_current_sign: str
    current_sign_reversed: bool

    def metadata(self) -> dict:
        payload = asdict(self)
        payload.pop("points")
        payload["delimiter"] = "tab" if self.delimiter == "\t" else self.delimiter
        return payload


def _decode(source: Path) -> Tuple[str, str]:
    raw = source.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode LAND export; save it as UTF-8 CSV or TXT")


def _matches_alias(canonical: str, value: str) -> bool:
    if value in ALIASES[canonical]:
        return True
    if canonical == "cycle":
        return "循环" in value or value.startswith("cycle")
    if canonical == "time":
        return any(token in value for token in ("总时间", "测试时间", "相对时间", "累计时间", "记录时间")) or any(
            token in value for token in ("totaltime", "elapsedtime", "testtime", "recordtime")
        )
    if canonical == "current":
        return "电流" in value or "current" in value
    if canonical == "voltage":
        return "电压" in value or "voltage" in value
    return False


def _column_mapping(headers: List[str], config: LandImportConfig) -> Optional[Dict[str, int]]:
    normalized = [_normalize(item) for item in headers]
    mapping: Dict[str, int] = {}
    for canonical in ("cycle", "time", "current", "voltage"):
        explicit = config.column_map.get(canonical)
        if explicit is not None:
            target = _normalize(explicit)
            if target not in normalized:
                return None
            mapping[canonical] = normalized.index(target)
            continue
        for index, value in enumerate(normalized):
            if _matches_alias(canonical, value):
                mapping[canonical] = index
                break
    return mapping if len(mapping) == 4 else None


def _find_header(text: str, config: LandImportConfig):
    best = None
    for delimiter in (",", "\t", ";"):
        rows = list(csv.reader(text.splitlines(), delimiter=delimiter))
        for index, row in enumerate(rows[:50]):
            mapping = _column_mapping(row, config)
            if mapping is not None:
                candidate = (index, -len(row), delimiter, rows, mapping)
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
                break
    if best is None:
        raise ValueError(
            "Cannot find LAND columns for cycle, time, current, and voltage. "
            "Export CSV/TXT or provide --cycle-column/--time-column/"
            "--current-column/--voltage-column."
        )
    header_index, _, delimiter, rows, mapping = best
    return header_index, delimiter, rows, mapping


def _detect_current_unit(header: str, configured: str) -> str:
    if configured != "auto":
        return configured
    normalized = _normalize(header)
    if "ma" in normalized:
        return "mA"
    if "ua" in normalized:
        return "uA"
    if normalized.endswith("a"):
        return "A"
    return "mA"


def _detect_voltage_unit(header: str, configured: str) -> str:
    if configured != "auto":
        return configured
    return "mV" if "mv" in _normalize(header) else "V"


def _detect_time_unit(header: str, configured: str) -> str:
    if configured != "auto":
        return configured
    normalized = _normalize(header)
    if normalized.endswith("ms"):
        return "ms"
    if "min" in normalized:
        return "min"
    if normalized.endswith("h") or "hour" in normalized:
        return "h"
    return "s"


def _parse_time(value: str, unit: str) -> float:
    text = value.strip()
    if ":" in text:
        day_match = re.fullmatch(r"(?:(\d+)\s*[dD天 ]\s*)?(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if day_match:
            days, hours, minutes, seconds = day_match.groups()
            return (float(days or 0) * 24 + float(hours)) * 3600 + float(minutes) * 60 + float(seconds)
        parts = text.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        raise ValueError("unsupported elapsed-time format")
    multiplier = {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0}[unit]
    return float(text) * multiplier


def load_land_export(path: Path, config: Optional[LandImportConfig] = None) -> LandImportResult:
    source = Path(path)
    config = config or LandImportConfig()
    if source.suffix.lower() in {".xls", ".xlsx"}:
        raise ValueError(
            "Excel files are not read without an added dependency. In LAND, export or save as UTF-8 CSV/TXT first."
        )
    if source.suffix.lower() not in {".csv", ".txt", ".tsv", ".dat"}:
        raise ValueError("Unsupported LAND file type; export it as CSV or TXT")

    text, encoding = _decode(source)
    header_index, delimiter, rows, mapping = _find_header(text, config)
    headers = rows[header_index]
    detected_columns = {name: headers[index].strip() for name, index in mapping.items()}
    current_unit = _detect_current_unit(headers[mapping["current"]], config.current_unit)
    voltage_unit = _detect_voltage_unit(headers[mapping["voltage"]], config.voltage_unit)
    time_unit = _detect_time_unit(headers[mapping["time"]], config.time_unit)
    current_factor = {"A": 1000.0, "mA": 1.0, "uA": 0.001}[current_unit]
    voltage_factor = {"V": 1.0, "mV": 0.001}[voltage_unit]
    sign_factor = 1.0 if config.charge_current_sign == "positive" else -1.0

    points: List[CyclingPoint] = []
    for row_index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        try:
            cycle_value = float(row[mapping["cycle"]].strip())
            cycle = int(cycle_value)
            time_s = _parse_time(row[mapping["time"]], time_unit)
            current_mA = float(row[mapping["current"]].strip()) * current_factor * sign_factor
            voltage_V = float(row[mapping["voltage"]].strip()) * voltage_factor
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError("Invalid LAND value at source row {}: {}".format(row_index, error)) from error
        values = (time_s, current_mA, voltage_V)
        if cycle <= 0 or cycle_value != cycle:
            raise ValueError("cycle must be a positive integer at source row {}".format(row_index))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite LAND value at source row {}".format(row_index))
        points.append(CyclingPoint(cycle, time_s, current_mA, voltage_V, row_index))

    if not points:
        raise ValueError("LAND export contains no data rows")
    return LandImportResult(
        points=points,
        detected_columns=detected_columns,
        detected_units={"time": time_unit, "current": current_unit, "voltage": voltage_unit},
        delimiter=delimiter,
        encoding=encoding,
        header_row=header_index + 1,
        charge_current_sign=config.charge_current_sign,
        current_sign_reversed=config.charge_current_sign == "negative",
    )
