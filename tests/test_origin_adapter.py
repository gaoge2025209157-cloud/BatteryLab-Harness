import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.origin_adapter import (
    OriginError,
    OriginInstallation,
    OriginJob,
    OriginJobError,
    OriginNotFound,
    OriginPlotFailed,
    OriginStatus,
    ascii_runtime_root,
    detect_release,
    find_origin,
    internal_version_from_orginfo,
    launch_origin,
    load_compatibility,
    render_launcher,
    resolve_release,
    supported_releases,
)


def supported():
    return supported_releases(PROJECT_ROOT)


def write_job(directory, *, with_inputs=True):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    curves = directory / "curves.csv"
    summary = directory / "summary.csv"
    if with_inputs:
        curves.write_text("cycle,direction\n1,charge\n", encoding="utf-8")
        summary.write_text("cycle,complete\n1,true\n", encoding="utf-8")
    job = {
        "curves_csv": str(curves),
        "summary_csv": str(summary),
        "project_path": str(directory / "电化学分析.opju"),
        "curve_png": str(directory / "充放电曲线.png"),
        "cycling_png": str(directory / "循环性能.png"),
        "status_path": str(directory / "origin_status.json"),
        "selected_cycles": [1],
        "representative_cycle_limit": 8,
    }
    path = directory / "origin_job.json"
    path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return path, job


class CompatibilityTests(unittest.TestCase):
    def test_supported_range_comes_from_the_compatibility_file(self):
        releases = supported()

        self.assertIn("2021", releases)
        self.assertIn("2026b", releases)
        self.assertEqual(len(releases), 12)
        payload = load_compatibility(PROJECT_ROOT)
        self.assertEqual(payload["locally_validated"], ["2026b"])

    def test_detect_release_accepts_only_the_supported_range(self):
        releases = supported()

        self.assertEqual(detect_release(r"D:\Origin2026b\Origin64.exe", releases), "2026b")
        self.assertEqual(detect_release("Origin 2023", releases), "2023")
        self.assertIsNone(detect_release("Origin 2019", releases))
        self.assertIsNone(detect_release("Origin2027", releases))
        self.assertIsNone(detect_release("Origin2026bb", releases))
        self.assertIsNone(detect_release("Origin64.exe", releases))


class OriginLocatorTests(unittest.TestCase):
    def test_missing_explicit_executable_is_rejected(self):
        with self.assertRaises(OriginNotFound):
            find_origin(PROJECT_ROOT, "C:/definitely/not/here/Origin64.exe")

    def test_explicit_executable_outside_the_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "Origin64.exe"
            candidate.write_bytes(b"")
            with self.assertRaises(OriginNotFound):
                find_origin(PROJECT_ROOT, str(candidate))

    def test_explicit_executable_inside_the_range_is_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "OriginLab" / "Origin2024b"
            folder.mkdir(parents=True)
            candidate = folder / "Origin64.exe"
            candidate.write_bytes(b"")

            installation = find_origin(PROJECT_ROOT, str(candidate))

            self.assertEqual(installation.release, "2024b")
            self.assertFalse(installation.locally_validated)

    def test_newest_supported_candidate_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidates = []
            for release in ("2021", "2023b", "2025"):
                folder = root / ("Origin" + release)
                folder.mkdir()
                target = folder / "Origin64.exe"
                target.write_bytes(b"")
                candidates.append(str(target))

            # 注册表扫描必须屏蔽：开发机或 CI 机器上可能真的装了 Origin，
            # 那样 find_origin 会选中本机的更新版本，这条断言就与机器状态相关了。
            with patch(
                "electrochem_harness.origin_adapter._registry_candidates",
                return_value=(),
            ):
                installation = find_origin(
                    PROJECT_ROOT, None, extra_candidates=candidates, search_drives=()
                )

            self.assertEqual(installation.release, "2025")

    def test_unsupported_candidates_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "Origin2019"
            folder.mkdir()
            candidate = folder / "Origin64.exe"
            candidate.write_bytes(b"")

            with patch(
                "electrochem_harness.origin_adapter._registry_candidates",
                return_value=(),
            ):
                with self.assertRaises(OriginNotFound):
                    find_origin(
                        PROJECT_ROOT,
                        None,
                        extra_candidates=[str(candidate)],
                        search_drives=(),
                    )


class ReleaseResolutionTests(unittest.TestCase):
    """用户可以把 Origin 装在任意目录，此时路径里没有年份。

    安装目录与 ``orginfo.txt`` 里只有内部版本号（``Ir103bSr2_243`` 即 10.3b），
    而配置与报告使用的是年份（2026b），两者必须能换算。
    """

    def test_parses_internal_version_strings(self):
        cases = {
            "Ir103bSr2_243": "10.3b",
            "Ir103": "10.3",
            "Ir100Sr0": "10.0",
            "Ir98Sr0": "9.8",
            "Ir95b": "9.5b",
            "garbage": None,
            "": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(internal_version_from_orginfo(raw), expected)

    def test_custom_install_directory_is_resolved_from_orginfo(self):
        with tempfile.TemporaryDirectory() as temp:
            # 目录名完全不含年份，正是 D:\hjp\origin 那种情况。
            install = Path(temp) / "origin"
            install.mkdir()
            exe = install / "Origin64.exe"
            exe.write_bytes(b"")
            (install / "orginfo.txt").write_text("Ir103bSr2_243", encoding="ascii")

            self.assertEqual(
                resolve_release(exe, ("2023", "2026", "2026b")), "2026b"
            )

    def test_directory_name_wins_over_orginfo(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "Origin2023"
            install.mkdir()
            exe = install / "Origin64.exe"
            exe.write_bytes(b"")
            (install / "orginfo.txt").write_text("Ir103bSr2_243", encoding="ascii")

            self.assertEqual(resolve_release(exe, ("2023", "2026b")), "2023")

    def test_unknown_release_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "origin"
            install.mkdir()
            exe = install / "Origin64.exe"
            exe.write_bytes(b"")

            self.assertIsNone(resolve_release(exe, ("2026b",)))

    def test_release_outside_supported_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            install = Path(temp) / "origin"
            install.mkdir()
            exe = install / "Origin64.exe"
            exe.write_bytes(b"")
            (install / "orginfo.txt").write_text("Ir97Sr0", encoding="ascii")

            # 9.7 对应 2020，不在 2021–2026b 范围内。
            self.assertIsNone(resolve_release(exe, ("2026b",)))


class OriginJobTests(unittest.TestCase):
    def test_every_declared_key_is_required(self):
        with self.assertRaises(OriginJobError):
            OriginJob.from_dict({"curves_csv": "a.csv"})

    def test_non_string_paths_are_rejected(self):
        payload = {
            "curves_csv": Path("a.csv"),
            "summary_csv": "b.csv",
            "project_path": "c.opju",
            "curve_png": "d.png",
            "cycling_png": "e.png",
            "status_path": "f.json",
        }
        with self.assertRaises(OriginJobError):
            OriginJob.from_dict(payload)

    def test_missing_file_is_reported_as_a_job_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(OriginJobError):
                OriginJob.read(Path(temp) / "origin_job.json")

    def test_malformed_json_is_reported_as_a_job_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "origin_job.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(OriginJobError):
                OriginJob.read(path)

    def test_round_trip_keeps_the_representative_cycle_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            path, _ = write_job(temp)
            job = OriginJob.read(path)

            self.assertEqual(job.selected_cycles, (1,))
            self.assertEqual(job.representative_cycle_limit, 8)
            self.assertEqual(len(job.expected_outputs()), 4)


class OriginStatusTests(unittest.TestCase):
    def test_ok_must_be_boolean(self):
        with self.assertRaises(OriginPlotFailed):
            OriginStatus.from_dict({"origin_release": "2026b"})

    def test_failure_status_preserves_the_error_text(self):
        status = OriginStatus.from_dict({"ok": False, "error": "boom"})

        self.assertFalse(status.ok)
        self.assertEqual(status.error, "boom")

    def test_missing_status_file_is_a_plot_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(OriginPlotFailed):
                OriginStatus.read(Path(temp) / "origin_status.json")

    def test_warnings_are_normalised_to_a_tuple(self):
        status = OriginStatus.from_dict(
            {"ok": True, "compatibility_warnings": ["a", "b"]}
        )

        self.assertEqual(status.warnings, ("a", "b"))


class LauncherScriptTests(unittest.TestCase):
    def test_launcher_script_only_starts_origin_and_hands_over_the_job(self):
        script = render_launcher(
            origin_exe=Path(r"C:\Program Files\OriginLab\Origin2026b\Origin64.exe"),
            release="2026b",
            job_path=Path(r"C:\Temp\ec\origin_job.json"),
            script_path="C:/Temp/ec/origin_plot.py",
            status_path=Path(r"C:\Temp\ec\origin_status.json"),
            timeout_seconds=90,
        )

        self.assertIn("Origin.ApplicationSI", script)
        self.assertIn("string ec_job$=", script)
        self.assertIn("run -pyf", script)
        self.assertIn("Origin2026b", script)
        self.assertIn("$timeout = 90", script)
        self.assertNotIn("python.exe", script)
        self.assertNotIn("未知", script)

    def test_single_quotes_in_paths_are_escaped(self):
        script = render_launcher(
            origin_exe=Path("C:/O'Brien/Origin64.exe"),
            release="2023",
            job_path=Path("C:/Temp/origin_job.json"),
            script_path="C:/Temp/origin_plot.py",
            status_path=Path("C:/Temp/origin_status.json"),
        )

        self.assertIn("$originExe = 'C:/O''Brien/Origin64.exe'", script)


class RuntimeRootTests(unittest.TestCase):
    def test_non_ascii_runtime_directories_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            non_ascii = Path(temp) / "中文目录"
            ascii_dir = Path(temp) / "ascii_runtime"

            chosen = ascii_runtime_root([non_ascii, ascii_dir])

            self.assertEqual(chosen, ascii_dir)
            self.assertTrue(ascii_dir.is_dir())

    def test_no_ascii_candidate_is_a_reviewable_error(self):
        with self.assertRaises(OriginError):
            ascii_runtime_root([Path("C:/中文"), None])


class LaunchOriginTests(unittest.TestCase):
    def _installation(self, root):
        executable = Path(root) / "OriginLab" / "Origin2026b" / "Origin64.exe"
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"")
        return OriginInstallation(executable, "2026b", True)

    def test_successful_run_returns_status_and_verifies_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_path, job = write_job(root / "artifacts")
            installation = self._installation(root)
            seen = {}

            def runner(command, *, timeout_seconds, checkpoint=None):
                seen["command"] = command
                if checkpoint is not None:
                    checkpoint()
                for key in ("project_path", "curve_png", "cycling_png"):
                    Path(job[key]).write_bytes(b"stub")
                Path(job["status_path"]).write_text(
                    json.dumps({"ok": True, "origin_release": "2026b"}),
                    encoding="utf-8",
                )
                return 0

            status = launch_origin(
                job_path,
                PROJECT_ROOT,
                locator=lambda project_root, exe: installation,
                runner=runner,
                runtime_candidates=[root / "runtime"],
            )

            self.assertTrue(status.ok)
            self.assertEqual(status.origin_release, "2026b")
            self.assertIn("powershell.exe", seen["command"][0].lower())
            self.assertTrue(Path(job["curve_png"]).is_file())

    def test_reported_failure_raises_with_the_origin_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_path, job = write_job(root / "artifacts")
            installation = self._installation(root)

            def runner(command, *, timeout_seconds, checkpoint=None):
                Path(job["status_path"]).write_text(
                    json.dumps({"ok": False, "error": "originpro import failed"}),
                    encoding="utf-8",
                )
                return 1

            with self.assertRaises(OriginPlotFailed) as caught:
                launch_origin(
                    job_path,
                    PROJECT_ROOT,
                    locator=lambda project_root, exe: installation,
                    runner=runner,
                    runtime_candidates=[root / "runtime"],
                )

            self.assertIn("originpro import failed", str(caught.exception))

    def test_success_without_figures_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_path, job = write_job(root / "artifacts")
            installation = self._installation(root)

            def runner(command, *, timeout_seconds, checkpoint=None):
                Path(job["status_path"]).write_text(
                    json.dumps({"ok": True}), encoding="utf-8"
                )
                return 0

            with self.assertRaises(OriginPlotFailed) as caught:
                launch_origin(
                    job_path,
                    PROJECT_ROOT,
                    locator=lambda project_root, exe: installation,
                    runner=runner,
                    runtime_candidates=[root / "runtime"],
                )

            self.assertIn("did not write", str(caught.exception))

    def test_missing_curve_input_stops_before_locating_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_path, _ = write_job(root / "artifacts", with_inputs=False)
            calls = []

            with self.assertRaises(OriginJobError):
                launch_origin(
                    job_path,
                    PROJECT_ROOT,
                    locator=lambda *args: calls.append(args),
                    runner=lambda *a, **k: 0,
                )

            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
