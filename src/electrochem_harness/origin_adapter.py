"""Origin 2021-2026b adapter for the controlled Harness tool registry.

Phase 5 splits Origin out of the analysis pipeline: this module owns *only*
project generation, so a missing or failing Origin can degrade one tool without
touching the report, the metrics, or the drawing CSV.

Two rules keep the adapter auditable:

1. It never guesses an Origin release. The supported range comes from
   ``origin_compat.json``, and only releases listed in ``locally_validated`` may
   be described as machine-tested.
2. It never runs an opaque analysis script. The only thing handed to Origin is
   ``origin_plot.py`` plus a job file that this project already generated, and
   the outcome is read back from ``origin_status.json`` instead of from console
   output.
"""

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple

try:  # Windows-only; the adapter still imports on other platforms for testing.
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None


SUPPORTED_SCHEMA_VERSION = 1
ORIGIN_PROCESS_NAME = "Origin64.exe"
ORIGIN_PLOT_SCRIPT = "origin_plot.py"
DEFAULT_TIMEOUT_SECONDS = 120.0
_RELEASE_PATTERN = re.compile(r"(?<!\d)(202[1-6]b?)(?![\dbB])")
_PRINTABLE_ASCII = re.compile(r"^[\x20-\x7e]+$")


class OriginError(RuntimeError):
    """Base error for Origin availability or plotting failures."""


class OriginNotFound(OriginError):
    """Raised when no supported Origin installation can be resolved."""


class OriginJobError(OriginError):
    """Raised when the generated Origin job file is missing or malformed."""


class OriginPlotFailed(OriginError):
    """Raised when Origin ran but did not produce a valid status and outputs."""


@dataclass(frozen=True)
class OriginInstallation:
    """A resolved ``Origin64.exe`` plus the release it was detected as."""

    path: Path
    release: str
    locally_validated: bool = False

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "path": str(self.path),
            "release": self.release,
            "locally_validated": self.locally_validated,
        }


@dataclass(frozen=True)
class OriginJob:
    """The four inputs and four outputs Origin is allowed to touch."""

    curves_csv: Path
    summary_csv: Path
    project_path: Path
    curve_png: Path
    cycling_png: Path
    status_path: Path
    selected_cycles: Tuple[int, ...] = ()
    representative_cycle_limit: int = 8

    REQUIRED_KEYS = (
        "curves_csv",
        "summary_csv",
        "project_path",
        "curve_png",
        "cycling_png",
        "status_path",
    )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OriginJob":
        if not isinstance(payload, Mapping):
            raise OriginJobError("origin_job.json must contain a JSON object.")
        missing = [key for key in cls.REQUIRED_KEYS if not payload.get(key)]
        if missing:
            raise OriginJobError(
                "origin_job.json is incomplete; missing: {}".format(", ".join(missing))
            )
        for key in cls.REQUIRED_KEYS:
            if not isinstance(payload[key], str):
                raise OriginJobError(
                    "origin_job.json field {} must be a path string.".format(key)
                )
        cycles = payload.get("selected_cycles") or ()
        if not isinstance(cycles, (list, tuple)):
            raise OriginJobError("origin_job.json selected_cycles must be a list.")
        limit = payload.get("representative_cycle_limit", 8)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise OriginJobError("origin_job.json representative_cycle_limit is invalid.")
        return cls(
            curves_csv=Path(payload["curves_csv"]),
            summary_csv=Path(payload["summary_csv"]),
            project_path=Path(payload["project_path"]),
            curve_png=Path(payload["curve_png"]),
            cycling_png=Path(payload["cycling_png"]),
            status_path=Path(payload["status_path"]),
            selected_cycles=tuple(int(item) for item in cycles),
            representative_cycle_limit=limit,
        )

    @classmethod
    def read(cls, path: Path) -> "OriginJob":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as error:
            raise OriginJobError(
                "Origin job file is missing: {}".format(path)
            ) from error
        except json.JSONDecodeError as error:
            raise OriginJobError(
                "Origin job file is not valid JSON: {}".format(path)
            ) from error
        return cls.from_dict(payload)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "curves_csv": str(self.curves_csv),
            "summary_csv": str(self.summary_csv),
            "project_path": str(self.project_path),
            "curve_png": str(self.curve_png),
            "cycling_png": str(self.cycling_png),
            "status_path": str(self.status_path),
            "selected_cycles": list(self.selected_cycles),
            "representative_cycle_limit": self.representative_cycle_limit,
        }

    def expected_outputs(self) -> Tuple[Path, ...]:
        return (
            self.project_path,
            self.curve_png,
            self.cycling_png,
            self.status_path,
        )


@dataclass(frozen=True)
class OriginStatus:
    """Content of ``origin_status.json`` written by ``origin_plot.py``."""

    ok: bool
    project: Optional[str] = None
    origin_release: str = "unknown"
    originpro_version: str = "unknown"
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OriginStatus":
        if not isinstance(payload, Mapping):
            raise OriginPlotFailed("origin_status.json must contain a JSON object.")
        if not isinstance(payload.get("ok"), bool):
            raise OriginPlotFailed("origin_status.json is missing a boolean 'ok'.")
        warnings = payload.get("compatibility_warnings") or ()
        if isinstance(warnings, str):
            warnings = (warnings,)
        return cls(
            ok=bool(payload["ok"]),
            project=None if payload.get("project") is None else str(payload["project"]),
            origin_release=str(payload.get("origin_release") or "unknown"),
            originpro_version=str(payload.get("originpro_version") or "unknown"),
            warnings=tuple(str(item) for item in warnings),
            error=None if payload.get("error") is None else str(payload["error"]),
        )

    @classmethod
    def read(cls, path: Path) -> "OriginStatus":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as error:
            raise OriginPlotFailed(
                "Origin did not produce a status file: {}".format(path)
            ) from error
        except json.JSONDecodeError as error:
            raise OriginPlotFailed(
                "Origin status file is not valid JSON: {}".format(path)
            ) from error
        return cls.from_dict(payload)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "ok": self.ok,
            "project": self.project,
            "origin_release": self.origin_release,
            "originpro_version": self.originpro_version,
            "compatibility_warnings": list(self.warnings),
            "error": self.error,
        }


def load_compatibility(project_root: Path) -> Mapping[str, Any]:
    """Read and validate ``origin_compat.json``."""

    path = Path(project_root) / "origin_compat.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise OriginError("origin_compat.json is missing.") from error
    except json.JSONDecodeError as error:
        raise OriginError("origin_compat.json is not valid JSON.") from error
    if not isinstance(payload, Mapping):
        raise OriginError("origin_compat.json must contain a JSON object.")
    if payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise OriginError(
            "origin_compat.json schema_version must be {}.".format(
                SUPPORTED_SCHEMA_VERSION
            )
        )
    releases = payload.get("supported_releases")
    if not isinstance(releases, list) or not releases:
        raise OriginError("origin_compat.json must list supported_releases.")
    validated = payload.get("locally_validated", [])
    if not isinstance(validated, list):
        raise OriginError("origin_compat.json locally_validated must be a list.")
    unknown = sorted(set(validated) - {str(item).lower() for item in releases})
    if unknown:
        raise OriginError(
            "origin_compat.json locally_validated contains unsupported releases: {}".format(
                ", ".join(unknown)
            )
        )
    return payload


def supported_releases(project_root: Path) -> Tuple[str, ...]:
    payload = load_compatibility(project_root)
    return tuple(str(item).lower() for item in payload["supported_releases"])


def detect_release(text: str, supported: Iterable[str]) -> Optional[str]:
    """Return the release named in ``text`` when it is inside the supported range."""

    allowed = {str(item).lower() for item in supported}
    match = _RELEASE_PATTERN.search(str(text or ""))
    if not match:
        return None
    release = match.group(1).lower()
    return release if release in allowed else None


def _release_score(release: str) -> Tuple[int, int]:
    year = int(release[:4])
    return year, 1 if release.endswith("b") else 0


def _registry_candidates() -> Sequence[str]:
    if winreg is None:
        return ()
    found = []
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(
            winreg, "KEY_WOW64_32KEY", 0
        ):
            try:
                key = winreg.OpenKey(
                    root,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
                    + "\\"
                    + ORIGIN_PROCESS_NAME,
                    0,
                    winreg.KEY_READ | view,
                )
            except OSError:
                continue
            try:
                value, _ = winreg.QueryValueEx(key, "")
            except OSError:
                value = ""
            finally:
                key.Close()
            if value:
                found.append(str(value))
    return tuple(found)


def _filesystem_candidates(search_drives: Iterable[str]) -> Sequence[str]:
    """Return ``Origin64.exe`` paths found under the usual install roots.

    Each pattern is ``<parent>/<wildcard directory>/Origin64.exe``; the wildcard
    directory is expanded with ``Path.glob`` because a full path string cannot
    contain an unmatched wildcard and still be checked with ``is_file``.
    """

    bases = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(variable)
        if base:
            bases.append(Path(base) / "OriginLab")
    for drive in search_drives:
        bases.append(Path(drive + os.sep))

    found = []
    seen = set()
    for base in bases:
        if not base.is_dir():
            continue
        for directory in sorted(base.glob("Origin*")):
            target = directory / ORIGIN_PROCESS_NAME
            if target.is_file() and str(target) not in seen:
                seen.add(str(target))
                found.append(str(target))
    return found


def find_origin(
    project_root: Path,
    explicit_exe: Optional[str] = None,
    *,
    search_drives: Iterable[str] = ("C:", "D:", "E:"),
    extra_candidates: Iterable[str] = (),
) -> OriginInstallation:
    """Resolve a supported ``Origin64.exe``; never guess the release."""

    compatibility = load_compatibility(project_root)
    supported = tuple(str(item).lower() for item in compatibility["supported_releases"])
    validated = {str(item).lower() for item in compatibility.get("locally_validated", [])}

    if explicit_exe:
        candidate = Path(str(explicit_exe))
        if not candidate.is_file():
            raise OriginNotFound(
                "The supplied Origin executable does not exist: {}".format(explicit_exe)
            )
        release = detect_release(str(candidate), supported)
        if release is None:
            raise OriginNotFound(
                "The supplied Origin executable is outside the supported 2021-2026b "
                "range or its release cannot be detected: {}".format(explicit_exe)
            )
        return OriginInstallation(candidate.resolve(), release, release in validated)

    candidates = list(extra_candidates) + list(_registry_candidates())
    candidates.extend(_filesystem_candidates(search_drives))

    resolved = {}
    for text in candidates:
        path = Path(str(text))
        if not path.is_file():
            continue
        release = detect_release(str(path), supported)
        if release is None:
            continue
        resolved[str(path.resolve())] = release

    if not resolved:
        raise OriginNotFound(
            "No supported Origin installation was found. Supported releases are "
            "2021 through 2026b; pass an explicit Origin64.exe path or disable Origin."
        )

    best = max(resolved.items(), key=lambda item: _release_score(item[1]))
    release = best[1]
    return OriginInstallation(Path(best[0]), release, release in validated)


def ascii_runtime_root(candidates: Iterable[Optional[Path]]) -> Path:
    """Return the first writable ASCII-only directory for ``run -pyf``."""

    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate)
        if not _PRINTABLE_ASCII.match(text):
            continue
        try:
            path = Path(text)
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return path
    raise OriginError(
        "Origin requires an ASCII-only runtime directory for 'run -pyf'; "
        "set TEMP to an ASCII path (for example C:\\Temp)."
    )


def _ps_path(path) -> str:
    """Render a path for PowerShell with forward slashes.

    PowerShell accepts either separator, but forward slashes need no escaping in
    single-quoted strings and stay identical across platforms, so the generated
    launcher is stable and diffable.

    ``str(WindowsPath)`` would emit backslashes on Windows and forward slashes on
    POSIX, which makes the generated script depend on where it was produced and
    forces every downstream comparison to deal with both forms.
    """

    return Path(path).as_posix()


def _ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def render_launcher(
    *,
    origin_exe: Path,
    release: str,
    job_path: Path,
    script_path: Path,
    status_path: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Render the minimal PowerShell launcher that drives Origin through COM.

    The launcher only *starts* Origin and hands it the job file. All analysis,
    formatting and export logic stays in ``origin_plot.py`` and the outcome is
    judged from ``origin_status.json``, never from console text.
    """

    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$originExe = " + _ps_quote(_ps_path(origin_exe)),
            "$release = " + _ps_quote(release),
            "$job = " + _ps_quote(_ps_path(job_path)),
            "$script = " + _ps_quote(_ps_path(script_path)),
            "$status = " + _ps_quote(_ps_path(status_path)),
            "$timeout = " + str(int(timeout_seconds)),
            "if (Test-Path -LiteralPath $status) { Remove-Item -LiteralPath $status -Force }",
            "$running = Get-Process -Name 'Origin64' -ErrorAction SilentlyContinue |",
            "    Where-Object { $_.Path -eq $originExe } | Select-Object -First 1",
            "if (-not $running) {",
            "    $started = Start-Process -FilePath $originExe "
            "-WorkingDirectory (Split-Path -Parent $originExe) -PassThru",
            "    Start-Sleep -Seconds 10",
            "    $started.Refresh()",
            "    if ($started.HasExited) {",
            "        throw ('Origin {0} exited during startup (code {1}). "
            "Open it manually once, then rerun.' -f $release, $started.ExitCode)",
            "    }",
            "}",
            "$origin = New-Object -ComObject Origin.ApplicationSI",
            "$origin.Visible = 1",
            "$origin.Execute(('string ec_job$=\"{0}\";string ec_release$=\"{1}\";' "
            "-f $job, $release)) | Out-Null",
            "$origin.Execute(('run -pyf \"{0}\";' -f $script)) | Out-Null",
            "$deadline = (Get-Date).AddSeconds($timeout)",
            "while (-not (Test-Path -LiteralPath $status) -and (Get-Date) -lt $deadline) {",
            "    Start-Sleep -Milliseconds 500",
            "}",
            "if (-not (Test-Path -LiteralPath $status)) {",
            "    throw ('Origin did not produce a status file within {0} seconds.' -f $timeout)",
            "}",
            "exit 0",
            "",
        ]
    )


def _default_runner(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    checkpoint: Optional[Callable[[], None]] = None,
) -> int:
    """Run the launcher, polling so cooperative cancellation stays responsive."""

    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.monotonic() + float(timeout_seconds) + 10.0
    try:
        while True:
            if checkpoint is not None:
                try:
                    checkpoint()
                except BaseException:
                    process.kill()
                    process.wait(timeout=10)
                    raise
            code = process.poll()
            if code is not None:
                return int(code)
            if time.monotonic() > deadline:
                process.kill()
                process.wait(timeout=10)
                raise OriginPlotFailed(
                    "Origin launcher exceeded {:.0f} seconds.".format(timeout_seconds)
                )
            time.sleep(0.25)
    finally:
        if process.poll() is None:  # pragma: no cover - defensive
            process.kill()


def _prepare_runtime(
    project_root: Path,
    job: OriginJob,
    installation: OriginInstallation,
    timeout_seconds: float,
    candidates: Iterable[Optional[Path]],
) -> Tuple[Path, Path, Path]:
    """Stage the plot script, an ASCII job copy and the launcher."""

    root = ascii_runtime_root(candidates)
    runtime = root / "ElectrochemHarnessOrigin-{}".format(os.getpid())
    if runtime.exists():
        shutil.rmtree(runtime, ignore_errors=True)
    runtime.mkdir(parents=True, exist_ok=True)

    script_destination = runtime / ORIGIN_PLOT_SCRIPT
    source_script = Path(project_root) / ORIGIN_PLOT_SCRIPT
    if not source_script.is_file():
        raise OriginError("{} is missing from the project root.".format(ORIGIN_PLOT_SCRIPT))
    shutil.copyfile(source_script, script_destination)

    # LabTalk string variables are not reliably Unicode-safe, so the job file is
    # copied into the ASCII runtime directory before Origin is told about it.
    job_destination = runtime / "origin_job.json"
    job_destination.write_text(
        json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    launcher = runtime / "launch_origin.ps1"
    launcher.write_text(
        render_launcher(
            origin_exe=installation.path,
            release=installation.release,
            job_path=job_destination,
            script_path=script_destination.as_posix(),
            status_path=job.status_path,
            timeout_seconds=timeout_seconds,
        ),
        encoding="utf-8",
    )
    return runtime, launcher, job_destination


def launch_origin(
    job_path: Path,
    project_root: Path,
    *,
    explicit_exe: Optional[str] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    checkpoint: Optional[Callable[[], None]] = None,
    locator: Optional[Callable[..., OriginInstallation]] = None,
    runner: Optional[Callable[..., int]] = None,
    runtime_candidates: Optional[Iterable[Optional[Path]]] = None,
) -> OriginStatus:
    """Generate the Origin project and figures, or raise a reviewable failure."""

    job = OriginJob.read(job_path)
    for dependency in (job.curves_csv, job.summary_csv):
        if not dependency.is_file():
            raise OriginJobError(
                "Origin input is missing: {}".format(dependency)
            )

    installation = (locator or find_origin)(project_root, explicit_exe)
    candidates = list(
        runtime_candidates
        if runtime_candidates is not None
        else (os.environ.get("TEMP"), os.environ.get("TMP"), project_root)
    )
    runtime, launcher, _ = _prepare_runtime(
        project_root, job, installation, timeout_seconds, candidates
    )
    try:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher),
        ]
        exit_code = (runner or _default_runner)(
            command, timeout_seconds=timeout_seconds, checkpoint=checkpoint
        )
        status = OriginStatus.read(job.status_path)
        if not status.ok:
            raise OriginPlotFailed(
                "Origin plotting failed (exit code {}): {}".format(
                    exit_code, status.error or "no error detail was written"
                )
            )
        missing = [str(item) for item in job.expected_outputs() if not item.is_file()]
        if missing:
            raise OriginPlotFailed(
                "Origin reported success but did not write: {}".format(", ".join(missing))
            )
        return status
    finally:
        shutil.rmtree(runtime, ignore_errors=True)
