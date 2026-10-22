import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from electrochem_harness.workflow import (
    ApprovalRequired,
    InvalidTransition,
    PlanHashMismatch,
    WorkflowState,
    WorkflowStateMachine,
)


class WorkflowStateMachineTests(unittest.TestCase):
    def test_starts_created_and_records_successful_transitions(self):
        machine = WorkflowStateMachine()

        self.assertEqual(machine.state, WorkflowState.CREATED)
        self.assertEqual(machine.history, ())

        machine.transition(WorkflowState.PREFLIGHT, reason="input selected")

        self.assertEqual(machine.state, WorkflowState.PREFLIGHT)
        self.assertEqual(len(machine.history), 1)
        self.assertEqual(machine.history[0].from_state, WorkflowState.CREATED)
        self.assertEqual(machine.history[0].to_state, WorkflowState.PREFLIGHT)
        self.assertEqual(machine.history[0].reason, "input selected")

    def test_happy_path_requires_plan_approval_before_running(self):
        machine = WorkflowStateMachine()
        machine.transition(WorkflowState.PREFLIGHT)
        machine.transition(WorkflowState.PLAN_READY, plan_hash="plan-v1")
        machine.transition(WorkflowState.AWAITING_APPROVAL)

        with self.assertRaises(ApprovalRequired):
            machine.transition(WorkflowState.RUNNING)

        machine.approve("plan-v1")
        machine.transition(WorkflowState.RUNNING)
        machine.transition(WorkflowState.VALIDATING)
        machine.transition(WorkflowState.COMPLETED)

        self.assertEqual(machine.state, WorkflowState.COMPLETED)

    def test_approval_must_match_current_plan_hash(self):
        machine = self._awaiting_approval("plan-v1")

        with self.assertRaises(PlanHashMismatch):
            machine.approve("plan-v2")

        self.assertFalse(machine.is_approved)
        self.assertEqual(machine.state, WorkflowState.AWAITING_APPROVAL)

    def test_replacing_plan_invalidates_approval_and_returns_to_plan_ready(self):
        machine = self._awaiting_approval("plan-v1")
        machine.approve("plan-v1")

        machine.replace_plan("plan-v2", reason="output scope changed")

        self.assertEqual(machine.state, WorkflowState.PLAN_READY)
        self.assertEqual(machine.current_plan_hash, "plan-v2")
        self.assertFalse(machine.is_approved)
        machine.transition(WorkflowState.AWAITING_APPROVAL)
        with self.assertRaises(ApprovalRequired):
            machine.transition(WorkflowState.RUNNING)

    def test_blocked_input_can_only_restart_preflight_or_cancel(self):
        machine = WorkflowStateMachine()
        machine.transition(WorkflowState.PREFLIGHT)
        machine.transition(WorkflowState.BLOCKED, reason="time column missing")

        with self.assertRaises(InvalidTransition):
            machine.transition(WorkflowState.RUNNING)

        machine.transition(WorkflowState.PREFLIGHT, reason="input corrected")
        self.assertEqual(machine.state, WorkflowState.PREFLIGHT)

    def test_reentering_preflight_clears_plan_and_approval(self):
        machine = self._awaiting_approval("plan-v1")
        machine.approve("plan-v1")

        machine.transition(WorkflowState.PREFLIGHT, reason="metadata changed")

        self.assertIsNone(machine.current_plan_hash)
        self.assertFalse(machine.is_approved)

    def test_warning_completion_is_only_reachable_after_validation(self):
        machine = self._running()

        with self.assertRaises(InvalidTransition):
            machine.transition(WorkflowState.COMPLETED_WITH_WARNINGS)

        machine.transition(WorkflowState.VALIDATING)
        machine.transition(WorkflowState.COMPLETED_WITH_WARNINGS)
        self.assertEqual(machine.state, WorkflowState.COMPLETED_WITH_WARNINGS)

    def test_cancel_is_distinct_and_terminal(self):
        machine = WorkflowStateMachine()
        machine.transition(WorkflowState.PREFLIGHT)
        machine.transition(WorkflowState.CANCELLED, reason="user cancelled")

        self.assertEqual(machine.state, WorkflowState.CANCELLED)
        with self.assertRaises(InvalidTransition):
            machine.transition(WorkflowState.FAILED)

    def test_failed_state_is_terminal(self):
        machine = self._running()
        machine.transition(WorkflowState.FAILED, reason="metric tool failed")

        with self.assertRaises(InvalidTransition):
            machine.transition(WorkflowState.PREFLIGHT)

    def test_invalid_operations_do_not_mutate_state_or_history(self):
        machine = WorkflowStateMachine()

        with self.assertRaises(InvalidTransition):
            machine.transition(WorkflowState.RUNNING)

        self.assertEqual(machine.state, WorkflowState.CREATED)
        self.assertEqual(machine.history, ())

    def test_plan_ready_requires_nonempty_hash(self):
        machine = WorkflowStateMachine()
        machine.transition(WorkflowState.PREFLIGHT)

        with self.assertRaisesRegex(ValueError, "plan_hash"):
            machine.transition(WorkflowState.PLAN_READY, plan_hash="  ")

        self.assertEqual(machine.state, WorkflowState.PREFLIGHT)

    def test_snapshot_is_json_ready_and_does_not_expose_approval_hash(self):
        machine = self._awaiting_approval("plan-v1")
        machine.approve("plan-v1")

        snapshot = machine.to_dict()

        self.assertEqual(snapshot["state"], "awaiting_approval")
        self.assertEqual(snapshot["current_plan_hash"], "plan-v1")
        self.assertTrue(snapshot["is_approved"])
        self.assertNotIn("approved_plan_hash", snapshot)
        self.assertEqual(snapshot["history"][-1]["to_state"], "awaiting_approval")

    def _awaiting_approval(self, plan_hash):
        machine = WorkflowStateMachine()
        machine.transition(WorkflowState.PREFLIGHT)
        machine.transition(WorkflowState.PLAN_READY, plan_hash=plan_hash)
        machine.transition(WorkflowState.AWAITING_APPROVAL)
        return machine

    def _running(self):
        machine = self._awaiting_approval("plan-v1")
        machine.approve("plan-v1")
        machine.transition(WorkflowState.RUNNING)
        return machine


if __name__ == "__main__":
    unittest.main()
