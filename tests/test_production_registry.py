import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.land_curve import analyze_land_capacity_curve
from electrochem_harness.origin_adapter import OriginStatus
from electrochem_harness.production_registry import (
    ORIGIN_ARTIFACTS,
    RESEARCH_FIELDS,
    TOOL_ORDER,
    ToolchainInputs,
    build_production_registry,
    tool_declarations,
)
from electrochem_harness.tool_registry import (
    CancellationToken,
    FailurePolicy,
    ToolContext,
    ToolOutcome,
)


def write_capacity_curve(path):
    path.write_text(
        "测试时间/h,比容量/mAh/g,电压/V\n"
        "0,0,1.0\n"
        "1,10,2.0\n"
        "2,0,2.1\n"
        "3,9,1.0\n"
        "4,0,1.1\n"
        "5,5,2.0\n",
        encoding="utf-8",
    )


def metadata(**overrides):
    values = {name: "" for name in RESEARCH_FIELDS}
    values.update(
        {
            "battery_system": "Li-S",
            "active_material": "S/C",
            "cell_type": "coin cell",
            "counter_electrode": "Li",
            "test_current": "0.2C",
            "temperature": "25 C",
            "normalization_basis": "硫质量",
            "max_literature": 2,
        }
    )
    values.update(overrides)
    return values


def context_for(output_dir):
    return ToolContext(
        run_id="run-test",
        plan_hash="0" * 64,
        output_dir=Path(output_dir),
        cancellation=CancellationToken(),
    )


class ProductionRegistryDeclarationTests(unittest.TestCase):
    def test_declaration_order_matches_the_documented_tool_chain(self):
        declared = [item["tool_id"] for item in tool_declarations()]

        self.assertEqual(tuple(declared), TOOL_ORDER)
        self.assertEqual(len(set(declared)), len(declared))

    def test_registry_manifest_matches_the_static_declarations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "curve.csv"
            write_capacity_curve(source)
            registry = build_production_registry(
                ToolchainInputs(
                    source=source,
                    values=metadata(),
                    analysis_payload=analyze_land_capacity_curve(source),
                    project_root=PROJECT_ROOT,
                    knowledge_markdown=root / "knowledge.md",
                )
            )

            manifest = {item["tool_id"]: item for item in registry.manifest()}

            self.assertTrue(registry.sealed)
            self.assertEqual(tuple(manifest), TOOL_ORDER)
            for declared in tool_declarations():
                entry = manifest[declared["tool_id"]]
                self.assertEqual(
                    entry["requires_network"], declared["requires_network"], declared["tool_id"]
                )
                self.assertEqual(
                    entry["writes_output"], declared["writes_output"], declared["tool_id"]
                )
                self.assertEqual(
                    entry["failure_policy"], declared["failure_policy"], declared["tool_id"]
                )
                self.assertEqual(
                    entry["timeout_seconds"], declared["timeout_seconds"], declared["tool_id"]
                )

    def test_optional_stages_degrade_while_required_stages_fail(self):
        policies = {item["tool_id"]: item["failure_policy"] for item in tool_declarations()}

        self.assertEqual(policies["search_literature_metadata"], FailurePolicy.DEGRADE.value)
        self.assertEqual(policies["build_origin_project"], FailurePolicy.DEGRADE.value)
        self.assertEqual(policies["parse_land_text"], FailurePolicy.FAIL.value)
        self.assertEqual(policies["calculate_cycle_metrics"], FailurePolicy.FAIL.value)
        self.assertEqual(policies["build_scientific_report"], FailurePolicy.FAIL.value)

    def test_every_declared_artifact_is_a_relative_deliverable_name(self):
        for declared in tool_declarations():
            for name in declared["artifacts"]:
                self.assertNotIn("/", name)
                self.assertNotIn("\\", name)
                self.assertNotIn("..", name)

    def test_origin_stage_declares_the_four_reviewable_artifacts(self):
        origin = next(
            item for item in tool_declarations() if item["tool_id"] == "build_origin_project"
        )

        self.assertEqual(tuple(origin["artifacts"]), ORIGIN_ARTIFACTS)


class ProductionRegistryOriginToolTests(unittest.TestCase):
    def _registry(self, temp_root, launcher):
        source = Path(temp_root) / "curve.csv"
        write_capacity_curve(source)
        return build_production_registry(
            ToolchainInputs(
                source=source,
                values=metadata(),
                analysis_payload=analyze_land_capacity_curve(source),
                project_root=PROJECT_ROOT,
                knowledge_markdown=Path(temp_root) / "knowledge.md",
                origin_launcher=launcher,
                origin_exe="",
            )
        )

    def test_missing_job_file_degrades_with_a_local_work_message(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = self._registry(temp, lambda *a, **k: None)
            handler = registry.get("build_origin_project").handler

            with self.assertRaises(Exception) as caught:
                handler(context_for(Path(temp) / "artifacts"))

            message = str(caught.exception)
            self.assertIn("origin_job.json", message)
            self.assertIn("保留", message)

    def test_raw_current_curve_job_degrades_instead_of_inventing_a_project(self):
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "origin_job.json").write_text(
                json.dumps(
                    {"curves_csv": str(artifacts / "Origin_充放电曲线数据.csv")},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            registry = self._registry(temp, lambda *a, **k: None)
            handler = registry.get("build_origin_project").handler

            with self.assertRaises(Exception) as caught:
                handler(context_for(artifacts))

            message = str(caught.exception)
            self.assertIn("尚未生成可执行的 Origin 作业", message)
            self.assertIn("保留", message)

    def test_successful_launch_returns_artifacts_and_warnings(self):
        captured = {}

        def launcher(job_path, project_root, **kwargs):
            captured["job_path"] = job_path
            captured["explicit_exe"] = kwargs.get("explicit_exe")
            captured["timeout"] = kwargs.get("timeout_seconds")
            return OriginStatus(
                ok=True,
                project="电化学分析.opju",
                origin_release="2026b",
                originpro_version="1.2.3",
                warnings=("save_fig(width=...) is unavailable",),
            )

        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "artifacts"
            artifacts.mkdir(parents=True)
            job = {
                "curves_csv": str(artifacts / "Origin_充放电曲线数据.csv"),
                "summary_csv": str(artifacts / "关键参数.csv"),
                "project_path": str(artifacts / "电化学分析.opju"),
                "curve_png": str(artifacts / "充放电曲线.png"),
                "cycling_png": str(artifacts / "循环性能.png"),
                "status_path": str(artifacts / "origin_status.json"),
            }
            (artifacts / "origin_job.json").write_text(
                json.dumps(job, ensure_ascii=False), encoding="utf-8"
            )
            registry = self._registry(temp, launcher)
            handler = registry.get("build_origin_project").handler

            outcome = handler(context_for(artifacts))

            self.assertIsInstance(outcome, ToolOutcome)
            self.assertEqual(outcome.value["origin_release"], "2026b")
            self.assertEqual(len(outcome.artifacts), 4)
            self.assertEqual(captured["job_path"], artifacts / "origin_job.json")
            self.assertIsNone(captured["explicit_exe"])
            self.assertTrue(outcome.warnings)
            self.assertIn("save_fig", outcome.warnings[0])

    def test_declared_origin_executable_is_passed_to_the_adapter(self):
        captured = {}

        def launcher(job_path, project_root, **kwargs):
            captured.update(kwargs)
            return OriginStatus(ok=True, origin_release="2023")

        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "origin_job.json").write_text(
                json.dumps(
                    {
                        "curves_csv": "a.csv",
                        "summary_csv": "b.csv",
                        "project_path": "c.opju",
                        "curve_png": "d.png",
                        "cycling_png": "e.png",
                        "status_path": "f.json",
                    }
                ),
                encoding="utf-8",
            )
            source = Path(temp) / "curve.csv"
            write_capacity_curve(source)
            registry = build_production_registry(
                ToolchainInputs(
                    source=source,
                    values=metadata(),
                    analysis_payload=analyze_land_capacity_curve(source),
                    project_root=PROJECT_ROOT,
                    knowledge_markdown=Path(temp) / "knowledge.md",
                    origin_launcher=launcher,
                    origin_exe="E:/Apps/Origin/Origin64.exe",
                )
            )

            registry.get("build_origin_project").handler(context_for(artifacts))

            self.assertEqual(captured["explicit_exe"], "E:/Apps/Origin/Origin64.exe")


if __name__ == "__main__":
    unittest.main()
