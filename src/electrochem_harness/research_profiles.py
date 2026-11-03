"""Persist reusable experiment and research presets for the desktop workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


PROFILE_FIELDS = (
    "battery_system",
    "active_material",
    "cell_type",
    "counter_electrode",
    "test_current",
    "temperature",
    "research_domain",
    "research_background",
    "research_question",
    "local_fulltext_dir",
    "literature_year_from",
    "use_origin",
    "origin_plot_mode",
    "origin_exe",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").split())[:80]


def suggested_profile_name(values: Mapping[str, Any]) -> str:
    parts = [
        _clean_name(values.get("battery_system")),
        _clean_name(values.get("active_material")),
        _clean_name(values.get("temperature")),
    ]
    parts = [part for part in parts if part]
    if len(parts) >= 3:
        parts[-1] = parts[-1] + "°C"
    return " · ".join(parts)[:80] or "当前课题"


class ResearchProfileStore:
    """Small atomic JSON store; raw data paths and output paths are never saved."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _default(self) -> dict:
        return {"schema_version": self.SCHEMA_VERSION, "active_profile": "", "profiles": {}}

    def _read(self) -> dict:
        if not self.path.is_file():
            return self._default()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self._default()
        if payload.get("schema_version") != self.SCHEMA_VERSION or not isinstance(payload.get("profiles"), dict):
            return self._default()
        return payload

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def names(self) -> tuple[str, ...]:
        payload = self._read()
        return tuple(sorted(payload["profiles"], key=str.casefold))

    def active_name(self) -> str:
        payload = self._read()
        name = _clean_name(payload.get("active_profile"))
        return name if name in payload["profiles"] else ""

    def get(self, name: str) -> dict:
        payload = self._read()
        record = payload["profiles"].get(_clean_name(name), {})
        values = record.get("values", {}) if isinstance(record, dict) else {}
        return {field: values[field] for field in PROFILE_FIELDS if field in values}

    def active(self) -> dict:
        return self.get(self.active_name())

    def save(self, name: str, values: Mapping[str, Any], *, make_active: bool = True) -> str:
        normalized_name = _clean_name(name) or suggested_profile_name(values)
        payload = self._read()
        current = payload["profiles"].get(normalized_name, {})
        created_at = current.get("created_at") if isinstance(current, dict) else None
        clean_values = {}
        for field in PROFILE_FIELDS:
            if field not in values:
                continue
            value = values[field]
            if field in {"use_origin"}:
                clean_values[field] = bool(value)
            elif field == "literature_year_from":
                try:
                    clean_values[field] = int(value)
                except (TypeError, ValueError):
                    continue
            else:
                clean_values[field] = str(value or "").strip()
        payload["profiles"][normalized_name] = {
            "created_at": created_at or _now(),
            "updated_at": _now(),
            "values": clean_values,
        }
        if make_active:
            payload["active_profile"] = normalized_name
        self._write(payload)
        return normalized_name

    def set_active(self, name: str) -> None:
        normalized_name = _clean_name(name)
        payload = self._read()
        if normalized_name not in payload["profiles"]:
            raise ValueError("课题配置不存在：{}".format(normalized_name))
        payload["active_profile"] = normalized_name
        self._write(payload)

    def delete(self, name: str) -> None:
        normalized_name = _clean_name(name)
        payload = self._read()
        payload["profiles"].pop(normalized_name, None)
        if payload.get("active_profile") == normalized_name:
            payload["active_profile"] = next(iter(payload["profiles"]), "")
        self._write(payload)
