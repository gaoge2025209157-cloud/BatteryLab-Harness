from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.storage import ResearchStore


class RunStageStorageTests(unittest.TestCase):
    def _store_with_run(self, directory: str) -> tuple[ResearchStore, str, str]:
        store = ResearchStore(Path(directory) / "research.sqlite3")
        project_id = store.create_project("Stage test", "P2O5", [])
        run_id = store.create_run(project_id, "a" * 64, {"temperature_C": 25}, "PENDING")
        return store, project_id, run_id

    def test_old_database_is_backed_up_once_before_idempotent_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite3"
            store, project_id, run_id = self._store_with_run(directory)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP TRIGGER experiment_runs_status_insert")
                connection.execute("DROP TRIGGER experiment_runs_status_update")
                connection.execute("PRAGMA ignore_check_constraints=ON")
                connection.execute("UPDATE experiment_runs SET status='NEEDS_REVIEW' WHERE run_id=?", (run_id,))
                connection.execute("UPDATE schema_meta SET value='4' WHERE key='schema_version'")
                connection.commit()

            migrated = ResearchStore(path)
            backup_files = list((path.parent / "backups").glob("*.sqlite3"))
            self.assertEqual(len(backup_files), 1)
            with closing(sqlite3.connect(backup_files[0])) as connection:
                self.assertEqual(connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], "4")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)

            migrated.migrate()
            ResearchStore(path)
            self.assertEqual(len(list((path.parent / "backups").glob("*.sqlite3"))), 1)
            self.assertEqual(migrated.list_projects()[0]["project_id"], project_id)
            self.assertEqual(migrated.get_run(run_id)["status"], "PENDING")
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], "5")
                self.assertEqual(connection.execute("SELECT legacy_status FROM experiment_runs WHERE run_id=?", (run_id,)).fetchone()[0], "NEEDS_REVIEW")

    def test_new_database_is_not_backed_up(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.sqlite3"
            ResearchStore(path)
            self.assertFalse((path.parent / "backups").exists())

    def test_stage_retry_preserves_append_only_history_and_scrubs_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _, run_id = self._store_with_run(directory)
            started = store.start_run_stage(run_id, "ANALYZE", {
                "source_file": "inputs/cycle.csv",
                "raw_points": [[0, 1], [1, 2]],
                "api_token": "top-secret",
            })
            self.assertEqual((started["status"], started["attempt"]), ("RUNNING", 1))
            self.assertEqual(started["recoverable_input"]["source_file"], "inputs/cycle.csv")
            self.assertNotIn("[[0, 1]", json.dumps(started["recoverable_input"]))
            self.assertNotIn("top-secret", json.dumps(started["recoverable_input"]))

            message = "failed at C:\\Users\\analyst\\secret.csv api_key=abc123 " + ("x" * 3000)
            failed = store.finish_run_stage(
                run_id, "ANALYZE", "FAILED", message, ["artifacts/failed-summary.json"]
            )
            self.assertEqual(failed["status"], "FAILED")
            self.assertLessEqual(len(failed["error"]), ResearchStore.MAX_STAGE_ERROR_LENGTH)
            self.assertNotIn("analyst", failed["error"])
            self.assertNotIn("abc123", failed["error"])

            retried = store.start_run_stage(run_id, "ANALYZE")
            self.assertEqual(retried["attempt"], 2)
            completed = store.finish_run_stage(
                run_id,
                "ANALYZE",
                "COMPLETED",
                artifact_paths=["artifacts/analysis.json", "plots/curve.png"],
                recoverable_input={"source_file": "inputs/cycle.csv", "delimiter": ","},
            )
            self.assertEqual(completed["artifact_paths"], ["artifacts/analysis.json", "plots/curve.png"])
            events = store.list_run_stage_events(run_id, "ANALYZE")
            self.assertEqual([event["new_status"] for event in events], ["RUNNING", "FAILED", "RUNNING", "COMPLETED"])
            self.assertEqual([event["attempt"] for event in events], [1, 1, 2, 2])
            self.assertEqual(store.get_run_stage(run_id, "ANALYZE")["status"], "COMPLETED")

            with closing(sqlite3.connect(store.path)) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE run_stage_events SET new_status='FAILED'")
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("DELETE FROM run_stage_events")

    def test_cancellation_status_validation_and_relative_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            store, project_id, run_id = self._store_with_run(directory)
            store.start_run_stage(run_id, "REPORT")
            cancelled = store.finish_run_stage(run_id, "REPORT", "CANCELLED", "cancelled by user")
            self.assertEqual(cancelled["status"], "CANCELLED")
            self.assertEqual(store.list_run_stages(run_id)[0]["attempt"], 1)

            with self.assertRaises(RuntimeError):
                store.finish_run_stage(run_id, "REPORT", "COMPLETED")
            with self.assertRaises(ValueError):
                store.update_run_status(run_id, "UNKNOWN")

            store.start_run_stage(run_id, "EXPORT")
            with self.assertRaises(ValueError):
                store.finish_run_stage(run_id, "EXPORT", "COMPLETED", artifact_paths=["C:\\private\\result.json"])
            self.assertEqual(store.get_run_stage(run_id, "EXPORT")["status"], "RUNNING")

            updated = store.update_run_status(run_id, "CANCELLED")
            self.assertEqual(updated["status"], "CANCELLED")
            self.assertEqual(store.list_runs(project_id, "CANCELLED")[0]["run_id"], run_id)


if __name__ == "__main__":
    unittest.main()
