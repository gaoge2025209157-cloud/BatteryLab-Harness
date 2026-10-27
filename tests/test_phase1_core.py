import json
import math
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.approval import (
    ApprovalExpired,
    ApprovalIntegrityError,
    ApprovalPlanMismatch,
    ApprovalScopeError,
    ApprovalStore,
    create_approval,
    revoke_approval,
    validate_approval,
)
from electrochem_harness.audit import AuditStore, verify_event_log
from electrochem_harness.controlled_run import ControlledAnalysisRun
from electrochem_harness.planning import build_analysis_plan
from electrochem_harness.tool_registry import (
    CancellationToken,
    ExecutionCancelled,
    FailurePolicy,
    ToolContext,
    ToolNotAllowed,
    ToolOutcome,
    ToolRegistry,
    ToolRegistrySealed,
    ToolSpec,
    ToolTimeout,
)
from electrochem_harness.validation import validate_run_outputs
from electrochem_harness.workflow import ApprovalRequired, WorkflowState


NOW = datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc)
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


def fixed_clock():
    return NOW


def make_plan(network=False, origin=False):
    return build_analysis_plan(
        input_identity=INPUT_IDENTITY,
        experiment_metadata=METADATA,
        network_enabled=network,
        network_fields=METADATA if network else None,
        origin_enabled=origin,
    )


class ApprovalPersistenceTests(unittest.TestCase):
    def test_round_trip_preserves_hash_scope_time_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approval.json"
            record = create_approval(
                "b" * 64,
                scopes=("local_analysis", "formal_output"),
                source="gui",
                now=NOW,
            )
            ApprovalStore(path).save(record)
            loaded = ApprovalStore(path).load()

            self.assertEqual(loaded, record)
            self.assertEqual(loaded.plan_hash, "b" * 64)
            self.assertEqual(loaded.scopes, ("formal_output", "local_analysis"))
            self.assertEqual(loaded.decided_at, "2026-10-14T08:00:00+00:00")
            self.assertEqual(loaded.source, "gui")

    def test_tampered_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approval.json"
            ApprovalStore(path).save(
                create_approval("b" * 64, scopes=("local_analysis",), now=NOW)
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["scopes"].append("network_access")
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ApprovalIntegrityError):
                ApprovalStore(path).load()

    def test_approval_file_uses_strict_schema_without_extra_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approval.json"
            record = create_approval("b" * 64, scopes=("local_analysis",), now=NOW)
            ApprovalStore(path).save(record)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["unexpected"] = "ignored data"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(ApprovalIntegrityError):
                ApprovalStore(path).load()

    def test_plan_change_expiry_and_missing_scope_invalidate_approval(self):
        record = create_approval(
            "b" * 64,
            scopes=("local_analysis",),
            now=NOW,
            expires_at=NOW + timedelta(minutes=30),
        )
        with self.assertRaises(ApprovalPlanMismatch):
            validate_approval(record, "c" * 64, now=NOW)
        with self.assertRaises(ApprovalExpired):
            validate_approval(record, "b" * 64, now=NOW + timedelta(hours=1))
        with self.assertRaises(ApprovalScopeError):
            validate_approval(
                record, "b" * 64, required_scopes=("network_access",), now=NOW
            )

    def test_revocation_is_persisted_and_cannot_authorize_execution(self):
        record = create_approval("b" * 64, scopes=("local_analysis",), now=NOW)
        revoked = revoke_approval(record, reason="user cancelled", now=NOW)

        self.assertFalse(revoked.approved)
        self.assertEqual(revoked.reason, "user cancelled")
        with self.assertRaises(ApprovalScopeError):
            validate_approval(revoked, "b" * 64, now=NOW)


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.plan_hash = "b" * 64
        self.approval = create_approval(
            self.plan_hash,
            scopes=("local_analysis", "formal_output"),
            now=NOW,
        )
        self.temp = tempfile.TemporaryDirectory()
        self.context = ToolContext(
            run_id="run-test",
            plan_hash=self.plan_hash,
            output_dir=Path(self.temp.name),
            cancellation=CancellationToken(),
            clock=fixed_clock,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_only_registered_and_planned_tools_can_execute(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("known", lambda context: 42))

        with self.assertRaises(ToolNotAllowed):
            registry.execute(
                "unknown", ("unknown",), self.approval, self.context
            )
        with self.assertRaises(ToolNotAllowed):
            registry.execute("known", ("other",), self.approval, self.context)

    def test_registry_can_be_sealed_against_runtime_tool_injection(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("known", lambda context: 42))
        registry.seal()

        with self.assertRaises(ToolRegistrySealed):
            registry.register(ToolSpec("late", lambda context: 1))

    def test_network_and_file_writes_require_separate_scopes(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "network",
                lambda context: 1,
                requires_network=True,
                writes_output=True,
            )
        )
        registry.seal()

        with self.assertRaises(ApprovalScopeError):
            registry.execute(
                "network", ("network",), self.approval, self.context
            )

    def test_success_is_normalized_and_retry_count_is_auditable(self):
        attempts = []

        def flaky(context):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("temporary")
            return {"value": 7}

        registry = ToolRegistry()
        registry.register(ToolSpec("flaky", flaky, max_retries=1))
        outcome = registry.execute(
            "flaky", ("flaky",), self.approval, self.context
        )

        self.assertEqual(outcome.value, {"value": 7})
        self.assertEqual(outcome.attempts, 2)

    def test_tool_arguments_use_an_explicit_allowlist(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec("known", lambda context, value=None: value, allowed_arguments=("value",))
        )

        with self.assertRaises(ToolNotAllowed):
            registry.execute(
                "known",
                ("known",),
                self.approval,
                self.context,
                arguments={"password": "secret"},
            )

    def test_cancellation_is_checked_before_tool_side_effect(self):
        called = []
        self.context.cancellation.cancel("user cancelled")
        registry = ToolRegistry()
        registry.register(ToolSpec("known", lambda context: called.append(True)))

        with self.assertRaises(ExecutionCancelled):
            registry.execute("known", ("known",), self.approval, self.context)
        self.assertEqual(called, [])

    def test_tool_timeout_is_enforced_after_the_registered_deadline(self):
        def slow(context):
            time.sleep(0.01)
            context.checkpoint()

        registry = ToolRegistry()
        registry.register(ToolSpec("slow", slow, timeout_seconds=0.001))

        with self.assertRaises(ToolTimeout):
            registry.execute("slow", ("slow",), self.approval, self.context)


class AuditAndValidationTests(unittest.TestCase):
    def test_event_log_is_hash_chained_and_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            audit = AuditStore(Path(temp), run_id="run-test", clock=fixed_clock)
            audit.initialize(make_plan())
            audit.append_event("state_transition", "preflight", {"reason": "start"})
            audit.append_event("state_transition", "plan_ready", {"reason": "ready"})

            self.assertTrue(verify_event_log(audit.events_path))
            lines = audit.events_path.read_text(encoding="utf-8").splitlines()
            first = json.loads(lines[0])
            first["details"]["reason"] = "tampered"
            lines[0] = json.dumps(first, ensure_ascii=False)
            audit.events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertFalse(verify_event_log(audit.events_path))

    def test_run_record_tracks_plan_approval_tools_degradation_and_final_state(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = make_plan(network=True)
            audit = AuditStore(Path(temp), run_id="run-test", clock=fixed_clock)
            audit.initialize(plan)
            approval = create_approval(
                plan.plan_hash,
                scopes=("local_analysis", "network_access", "formal_output"),
                now=NOW,
            )
            audit.save_approval(approval)
            audit.record_tool("parse_land_text", "success", 1, output={"rows": 4})
            audit.add_degradation("search_literature_metadata", "network unavailable")
            audit.finalize("completed_with_warnings", core_results={"cycles": 2})

            payload = json.loads(audit.run_record_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["plan_hash"], plan.plan_hash)
            self.assertEqual(payload["approval"]["record_hash"], approval.record_hash)
            self.assertEqual(payload["tools"][0]["tool_id"], "parse_land_text")
            self.assertEqual(payload["degradations"][0]["tool_id"], "search_literature_metadata")
            self.assertEqual(payload["state"], "completed_with_warnings")
            self.assertEqual(len(payload["core_results_hash"]), 64)
            self.assertTrue(payload["software_version"])
            self.assertEqual(len(payload["rules_version_sha256"]), 64)

    def test_audit_redacts_sensitive_mapping_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            audit = AuditStore(Path(temp), run_id="run-test", clock=fixed_clock)
            audit.initialize(make_plan())
            audit.record_tool(
                "parse_land_text",
                "success",
                1,
                arguments={"mode": "auto", "password": "secret"},
                duration_seconds=0.25,
                output={"password": "secret", "nested": {"authorization": "Bearer token"}},
            )
            payload = json.loads(audit.run_record_path.read_text(encoding="utf-8"))
            tool = payload["tools"][0]
            output = tool["output"]
            self.assertEqual(tool["arguments"]["mode"], "auto")
            self.assertEqual(tool["arguments"]["password"], "[REDACTED]")
            self.assertEqual(tool["duration_seconds"], 0.25)
            self.assertEqual(output["password"], "[REDACTED]")
            self.assertEqual(output["nested"]["authorization"], "[REDACTED]")

    def test_validation_rejects_nonfinite_numbers_and_missing_or_invalid_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "bad.json").write_text("not json", encoding="utf-8")
            result = validate_run_outputs(
                {"capacity": math.nan},
                output,
                expected_artifacts=("bad.json", "missing.csv"),
            )

            self.assertFalse(result.valid)
            codes = {issue.code for issue in result.issues}
            self.assertIn("nonfinite_number", codes)
            self.assertIn("invalid_json_artifact", codes)
            self.assertIn("missing_artifact", codes)

    def test_validation_hashes_valid_outputs_deterministically(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "result.json").write_text('{"ok": true}', encoding="utf-8")
            first = validate_run_outputs(
                {"cycles": [1, 2]}, output, expected_artifacts=("result.json",)
            )
            second = validate_run_outputs(
                {"cycles": [1, 2]}, output, expected_artifacts=("result.json",)
            )

            self.assertTrue(first.valid)
            self.assertEqual(first.core_results_hash, second.core_results_hash)
            self.assertEqual(first.artifacts[0].sha256, second.artifacts[0].sha256)


class ControlledRunIntegrationTests(unittest.TestCase):
    def _registry(self, fail_network=False, fail_origin=False, fail_parse=False):
        registry = ToolRegistry()

        def parse(context):
            if fail_parse:
                raise ValueError("parse failed")
            return {"rows": 10}

        def quality(context, parsed=None):
            return {"issues": []}

        def metrics(context, parsed=None):
            return {"cycles": [{"cycle": 1, "coulombic_efficiency": 0.99}]}

        def report(context, metrics=None):
            artifacts = []
            for name, content in (
                ("关键结论.txt", "关键指标\n循环：1\n"),
                ("关键参数报告.md", "# report\n"),
                ("关键参数.csv", "cycle,capacity\n1,100\n"),
                ("完整分析.json", '{"status":"ok"}'),
                ("Origin_充放电曲线数据.csv", "cycle,voltage\n1,3.0\n"),
                ("origin_job.json", '{"status_path":"origin_status.json"}'),
            ):
                path = context.output_dir / name
                path.write_text(content, encoding="utf-8")
                artifacts.append(path)
            return ToolOutcome(value={"report": "ok"}, artifacts=tuple(artifacts))

        def network(context):
            if fail_network:
                raise ConnectionError("network unavailable")
            artifacts = []
            for name, content in (
                ("文献证据.json", '{"records":[]}'),
                ("文献比较.csv", "doi,title\n"),
            ):
                path = context.output_dir / name
                path.write_text(content, encoding="utf-8")
                artifacts.append(path)
            return ToolOutcome(value={"records": []}, artifacts=tuple(artifacts))

        def origin(context):
            if fail_origin:
                raise RuntimeError("Origin unavailable")
            artifacts = []
            for name, content in (
                ("电化学分析.opju", "project"),
                ("充放电曲线.png", "png"),
                ("循环性能.png", "png"),
                ("origin_status.json", '{"ok":true}'),
            ):
                path = context.output_dir / name
                path.write_text(content, encoding="utf-8")
                artifacts.append(path)
            return ToolOutcome(value={"ok": True}, artifacts=tuple(artifacts))

        registry.register(ToolSpec("parse_land_text", parse))
        registry.register(ToolSpec("quality_check", quality))
        registry.register(ToolSpec("calculate_cycle_metrics", metrics))
        registry.register(
            ToolSpec(
                "search_literature_metadata",
                network,
                requires_network=True,
                writes_output=True,
                failure_policy=FailurePolicy.DEGRADE,
            )
        )
        registry.register(ToolSpec("build_scientific_report", report, writes_output=True))
        registry.register(
            ToolSpec(
                "build_origin_project",
                origin,
                writes_output=True,
                failure_policy=FailurePolicy.DEGRADE,
            )
        )
        registry.seal()
        return registry

    def test_unapproved_run_executes_no_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            run = ControlledAnalysisRun(
                make_plan(), self._registry(), Path(temp), run_id="run-test", clock=fixed_clock
            )
            with self.assertRaises(ApprovalRequired):
                run.execute()
            self.assertEqual(run.state, WorkflowState.AWAITING_APPROVAL)

    def test_full_success_is_completed_and_fully_traceable(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = make_plan(network=True, origin=True)
            run = ControlledAnalysisRun(
                plan, self._registry(), Path(temp), run_id="run-test", clock=fixed_clock
            )
            run.grant(
                create_approval(
                    plan.plan_hash,
                    scopes=("local_analysis", "network_access", "formal_output"),
                    now=NOW,
                )
            )
            result = run.execute()

            self.assertEqual(result.state, WorkflowState.COMPLETED)
            self.assertTrue(result.validation.valid)
            for name in ("plan.json", "approval.json", "events.jsonl", "run_record.json"):
                self.assertTrue((result.run_dir / name).exists(), name)
            self.assertTrue(verify_event_log(result.run_dir / "events.jsonl"))

    def test_network_and_origin_failures_preserve_local_results_as_warning_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = make_plan(network=True, origin=True)
            run = ControlledAnalysisRun(
                plan,
                self._registry(fail_network=True, fail_origin=True),
                Path(temp),
                run_id="run-test",
                clock=fixed_clock,
            )
            run.grant(
                create_approval(
                    plan.plan_hash,
                    scopes=("local_analysis", "network_access", "formal_output"),
                    now=NOW,
                )
            )
            result = run.execute()

            self.assertEqual(result.state, WorkflowState.COMPLETED_WITH_WARNINGS)
            self.assertEqual(result.outputs["build_scientific_report"]["report"], "ok")
            self.assertEqual(len(result.degradations), 2)
            self.assertTrue((result.run_dir / "artifacts" / "关键参数报告.md").exists())

    def test_required_tool_failure_is_failed_and_still_audited(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = make_plan()
            run = ControlledAnalysisRun(
                plan,
                self._registry(fail_parse=True),
                Path(temp),
                run_id="run-test",
                clock=fixed_clock,
            )
            run.grant(
                create_approval(
                    plan.plan_hash,
                    scopes=("local_analysis", "formal_output"),
                    now=NOW,
                )
            )
            result = run.execute()

            self.assertEqual(result.state, WorkflowState.FAILED)
            record = json.loads((result.run_dir / "run_record.json").read_text(encoding="utf-8"))
            self.assertEqual(record["state"], "failed")
            self.assertIn("parse failed", record["error"]["message"])

    def test_cancellation_has_distinct_terminal_state(self):
        with tempfile.TemporaryDirectory() as temp:
            plan = make_plan()
            token = CancellationToken()
            token.cancel("user cancelled")
            run = ControlledAnalysisRun(
                plan, self._registry(), Path(temp), run_id="run-test", clock=fixed_clock
            )
            run.grant(
                create_approval(
                    plan.plan_hash,
                    scopes=("local_analysis", "formal_output"),
                    now=NOW,
                )
            )
            result = run.execute(cancellation=token)

            self.assertEqual(result.state, WorkflowState.CANCELLED)
            self.assertNotEqual(result.state, WorkflowState.FAILED)


if __name__ == "__main__":
    unittest.main()
