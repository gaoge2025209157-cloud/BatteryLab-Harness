"""Deterministic validation for numeric results and generated artifacts."""

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str
    location: str = ""

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "location": self.location,
        }


@dataclass(frozen=True)
class ArtifactRecord:
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self):
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: Tuple[ValidationIssue, ...]
    artifacts: Tuple[ArtifactRecord, ...]
    core_results_hash: str

    def to_dict(self):
        return {
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "core_results_hash": self.core_results_hash,
        }


def validate_run_outputs(
    core_results: Any,
    output_dir: Path,
    *,
    expected_artifacts: Iterable[str],
    allowed_missing_artifacts: Iterable[str] = (),
) -> ValidationResult:
    """Validate finite numeric output and hash every present expected artifact."""

    issues = []
    _check_numbers(core_results, "$", issues)
    core_hash = _payload_hash(core_results)
    root = Path(output_dir).resolve()
    allowed_missing = set(allowed_missing_artifacts)
    artifacts = []
    for name in expected_artifacts:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            issues.append(
                ValidationIssue(
                    "unsafe_artifact_path",
                    "Expected artifact path must remain inside the run output directory.",
                    "error",
                    str(name),
                )
            )
            continue
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            issues.append(
                ValidationIssue(
                    "unsafe_artifact_path",
                    "Artifact resolves outside the run output directory.",
                    "error",
                    str(name),
                )
            )
            continue
        if not path.is_file():
            severity = "warning" if str(name) in allowed_missing else "error"
            issues.append(
                ValidationIssue(
                    "missing_artifact",
                    "Expected artifact was not generated.",
                    severity,
                    str(name),
                )
            )
            continue
        size = path.stat().st_size
        if size <= 0:
            issues.append(
                ValidationIssue(
                    "empty_artifact", "Generated artifact is empty.", "error", str(name)
                )
            )
        _validate_file_content(path, str(name), issues)
        artifacts.append(
            ArtifactRecord(str(name), size, hash_file(path))
        )
    valid = not any(issue.severity == "error" for issue in issues)
    return ValidationResult(valid, tuple(issues), tuple(artifacts), core_hash)


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _check_numbers(value: Any, location: str, issues) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            issues.append(
                ValidationIssue(
                    "nonfinite_number",
                    "Core numeric results must not contain NaN or infinity.",
                    "error",
                    location,
                )
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _check_numbers(item, "{}.{}".format(location, key), issues)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_numbers(item, "{}[{}]".format(location, index), issues)


def _payload_hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, Path):
        return str(value)
    raise TypeError("Value is not JSON serializable: {!r}".format(type(value)))


def _validate_file_content(path: Path, display_name: str, issues) -> None:
    suffix = path.suffix.casefold()
    try:
        if suffix == ".json":
            json.loads(path.read_text(encoding="utf-8-sig"))
        elif suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = csv.reader(handle)
                if next(rows, None) is None:
                    raise ValueError("CSV has no header row")
        elif suffix == ".md" and not path.read_text(encoding="utf-8").strip():
            raise ValueError("Markdown file is blank")
    except (UnicodeError, json.JSONDecodeError, csv.Error, ValueError) as error:
        code = "invalid_json_artifact" if suffix == ".json" else "invalid_artifact"
        issues.append(
            ValidationIssue(code, str(error), "error", display_name)
        )
