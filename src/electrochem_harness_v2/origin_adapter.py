"""Origin job manifest writer that fails closed when Origin output is absent."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Callable


@dataclass(frozen=True)
class OriginPlotResult:
    status: str
    manifest_path: Path
    project_path: Path
    image_paths: tuple[Path, ...]
    reason: str | None = None


def _safe_reason(value: str | None) -> str | None:
    if value is None:
        return None
    # Reports and manifests must remain portable and must not expose local paths.
    compact = re.sub(r"(?i)[a-z]:\\[^\r\n]+", "<local-path>", str(value))
    return " ".join(compact.split())[:800]


class OriginAdapter:
    """The only formal plot path. Missing Origin output is always PLOT_BLOCKED."""

    def __init__(self, script_path: Path | str, runner: Callable | None = None, origin_executable: Path | str | None = None):
        self.script_path = Path(script_path)
        self.origin_executable = Path(origin_executable) if origin_executable else None
        self.runner = runner or self._run_powershell

    def _run_powershell(self, script_path: Path, job_path: Path) -> None:
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path), "-JobPath", str(job_path)]
        if self.origin_executable:
            command.extend(["-OriginExe", str(self.origin_executable)])
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout or "Origin runner returned a non-zero exit code.").strip()
            raise RuntimeError(detail)

    def plot(self, run_dir: Path | str, curves_csv: Path | str, summary_csv: Path | str, run_id: str, raw_data_sha256: str, initial_curves_csv: Path | str | None = None) -> OriginPlotResult:
        base = Path(run_dir) / "origin"
        figures = Path(run_dir) / "figures"
        base.mkdir(parents=True, exist_ok=True)
        figures.mkdir(parents=True, exist_ok=True)
        project_path = base / "electrochemistry.opju"
        curve_png = figures / "charge_discharge.png"
        cycling_png = figures / "cycling.png"
        initial_png = figures / "initial_discharge.png"
        status_path = base / "origin_status.json"
        initial_status_path = base / "initial_origin_status.json"
        job_path = base / "origin_job.json"
        job = {
            "curves_csv": str(Path(curves_csv).resolve()), "summary_csv": str(Path(summary_csv).resolve()),
            "project_path": str(project_path.resolve()), "curve_png": str(curve_png.resolve()), "cycling_png": str(cycling_png.resolve()),
            "status_path": str(status_path.resolve()), "plot_mode": "both", "run_id": run_id, "raw_data_sha256": raw_data_sha256,
        }
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        has_initial_discharge = bool(initial_curves_csv and Path(initial_curves_csv).is_file() and Path(initial_curves_csv).stat().st_size > 80)
        reason = "Origin runner is unavailable."
        if self.runner and self.script_path.is_file():
            try:
                self.runner(self.script_path, job_path)
            except Exception as error:
                reason = "Origin runner failed: {}".format(error)
        elif self.script_path.is_file():
            reason = "Origin runner was not configured."
        if status_path.is_file():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                completed = bool(status.get("ok")) and all(path.is_file() and path.stat().st_size > 0 for path in (project_path, curve_png, cycling_png))
                if completed:
                    result_status, reason = "ORIGIN_PLOTTED", None
                else:
                    result_status = "PLOT_BLOCKED"
                    reason = str(status.get("error") or "Origin did not produce all required non-empty outputs.")
            except (OSError, json.JSONDecodeError) as error:
                result_status, reason = "PLOT_BLOCKED", "Origin status is invalid: {}".format(error)
        else:
            result_status = "PLOT_BLOCKED"
        image_paths = [curve_png, cycling_png]
        initial_discharge_status = "excluded_from_representative_cycle_plot; inspect audited source segment separately" if has_initial_discharge else "not_present"
        safe_reason = _safe_reason(reason)
        manifest = {"run_id": run_id, "raw_data_sha256": raw_data_sha256, "status": result_status, "reason": safe_reason, "job_file": job_path.name, "initial_discharge_status": initial_discharge_status, "opju": project_path.name, "figures": [path.name for path in image_paths]}
        manifest_path = base / "origin_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return OriginPlotResult(result_status, manifest_path, project_path, tuple(image_paths), safe_reason)
