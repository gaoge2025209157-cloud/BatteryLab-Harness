import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.models import QualityIssue
from electrochem_harness.planning import (
    BlockingPreflightError,
    UnsafeNetworkFieldError,
    build_analysis_plan,
    verify_plan_hash,
)
from electrochem_harness.workflow import WorkflowState, WorkflowStateMachine


INPUT_IDENTITY = {
    "display_path": "experiment.csv",
    "sha256": "a" * 64,
    "size_bytes": 1024,
}
METADATA = {
    "battery_system": "锂硫电池",
    "active_material": "S/C",
    "cell_type": "半电池",
    "counter_electrode": "Li",
    "test_current": "0.2 C",
    "temperature": "25 C",
    "normalization_basis": "硫质量",
}


class AnalysisPlanTests(unittest.TestCase):
    def test_plan_hash_is_stable_for_equivalent_inputs(self):
        first = build_analysis_plan(
            input_identity=INPUT_IDENTITY,
            experiment_metadata=METADATA,
        )
        second = build_analysis_plan(
            input_identity=dict(reversed(list(INPUT_IDENTITY.items()))),
            experiment_metadata=dict(reversed(list(METADATA.items()))),
        )

        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(first.plan_id, second.plan_id)
        self.assertTrue(verify_plan_hash(first))

    def test_plan_hash_changes_when_scientific_or_execution_scope_changes(self):
        baseline = self._plan()
        changed_metadata = build_analysis_plan(
            input_identity=INPUT_IDENTITY,
            experiment_metadata={**METADATA, "temperature": "60 C"},
        )
        changed_network = self._plan(network_enabled=True)
        changed_origin = self._plan(origin_enabled=True)

        self.assertNotEqual(baseline.plan_hash, changed_metadata.plan_hash)
        self.assertNotEqual(baseline.plan_hash, changed_network.plan_hash)
        self.assertNotEqual(baseline.plan_hash, changed_origin.plan_hash)

    def test_blocking_preflight_issue_prevents_plan_creation(self):
        issue = QualityIssue("missing_time", "缺少时间列", True)

        with self.assertRaisesRegex(BlockingPreflightError, "missing_time"):
            build_analysis_plan(
                input_identity=INPUT_IDENTITY,
                experiment_metadata=METADATA,
                preflight_issues=[issue],
            )

    def test_nonblocking_preflight_issue_is_preserved_in_plan(self):
        issue = QualityIssue("missing_temperature", "温度未填写", False)

        plan = build_analysis_plan(
            input_identity=INPUT_IDENTITY,
            experiment_metadata=METADATA,
            preflight_issues=[issue],
        )

        self.assertEqual(plan.preflight_issues[0]["code"], "missing_temperature")
        self.assertFalse(plan.preflight_issues[0]["blocking"])

    def test_network_plan_previews_only_public_research_fields(self):
        plan = self._plan(network_enabled=True)

        self.assertTrue(plan.network_enabled)
        self.assertEqual(dict(plan.network_fields), METADATA)
        self.assertIn("search_literature_metadata", plan.tools)
        self.assertIn("文献证据.json", plan.expected_artifacts)

    def test_network_plan_rejects_raw_paths_credentials_and_unknown_fields(self):
        for field in ("input_path", "password", "cookie", "raw_data"):
            with self.subTest(field=field):
                with self.assertRaises(UnsafeNetworkFieldError):
                    build_analysis_plan(
                        input_identity=INPUT_IDENTITY,
                        experiment_metadata=METADATA,
                        network_enabled=True,
                        network_fields={**METADATA, field: "secret"},
                    )

    def test_network_fields_are_rejected_when_network_is_disabled(self):
        with self.assertRaisesRegex(ValueError, "network_enabled"):
            build_analysis_plan(
                input_identity=INPUT_IDENTITY,
                experiment_metadata=METADATA,
                network_fields=METADATA,
            )

    def test_tools_and_artifacts_match_requested_execution_scope(self):
        local = self._plan()
        full = self._plan(network_enabled=True, origin_enabled=True)

        self.assertNotIn("search_literature_metadata", local.tools)
        self.assertNotIn("build_origin_project", local.tools)
        self.assertNotIn("电化学分析.opju", local.expected_artifacts)
        self.assertIn("search_literature_metadata", full.tools)
        self.assertIn("build_origin_project", full.tools)
        self.assertIn("电化学分析.opju", full.expected_artifacts)
        self.assertEqual(full.tools[-1], "build_origin_project")

    def test_plan_is_immutable_and_to_dict_is_json_ready(self):
        plan = self._plan(network_enabled=True)

        with self.assertRaises(TypeError):
            plan.experiment_metadata["temperature"] = "60 C"

        payload = plan.to_dict()
        json.dumps(payload, ensure_ascii=False)
        payload["experiment_metadata"]["temperature"] = "60 C"
        self.assertEqual(plan.experiment_metadata["temperature"], "25 C")

    def test_plan_hash_can_drive_state_machine_approval_gate(self):
        plan = self._plan(network_enabled=True)
        machine = WorkflowStateMachine()
        machine.transition(WorkflowState.PREFLIGHT)
        machine.transition(WorkflowState.PLAN_READY, plan_hash=plan.plan_hash)
        machine.transition(WorkflowState.AWAITING_APPROVAL)
        machine.approve(plan.plan_hash)
        machine.transition(WorkflowState.RUNNING)

        self.assertEqual(machine.state, WorkflowState.RUNNING)

    def test_input_identity_requires_real_sha256_and_nonnegative_size(self):
        for identity in (
            {**INPUT_IDENTITY, "sha256": "not-a-hash"},
            {**INPUT_IDENTITY, "size_bytes": -1},
            {"sha256": "a" * 64, "size_bytes": 1},
        ):
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    build_analysis_plan(
                        input_identity=identity,
                        experiment_metadata=METADATA,
                    )

    def _plan(self, network_enabled=False, origin_enabled=False):
        return build_analysis_plan(
            input_identity=INPUT_IDENTITY,
            experiment_metadata=METADATA,
            network_enabled=network_enabled,
            network_fields=METADATA if network_enabled else None,
            origin_enabled=origin_enabled,
        )


if __name__ == "__main__":
    unittest.main()
