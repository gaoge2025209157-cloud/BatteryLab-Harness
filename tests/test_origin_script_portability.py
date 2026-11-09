from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
WRAPPER = SCRIPTS_DIR / "origin_plot.py"
ENGINE = SCRIPTS_DIR / "origin_plot_engine.py"
RUNNER = SCRIPTS_DIR / "run_origin.ps1"


class OriginScriptPortabilityTests(unittest.TestCase):
    def test_wrapper_uses_repository_local_engine_without_legacy_absolute_path(self):
        wrapper_text = WRAPPER.read_text(encoding="utf-8")

        self.assertTrue(ENGINE.is_file(), "The repository-local Origin engine is missing.")
        self.assertIn('Path(__file__).resolve().with_name("origin_plot_engine.py")', wrapper_text)
        self.assertNotIn("电化学智能实验Harness", wrapper_text)
        self.assertIsNone(
            re.search(r"[A-Za-z]:[\\/]", wrapper_text),
            "The wrapper must not contain a Windows absolute path.",
        )

    def test_runner_stages_wrapper_and_local_engine_together(self):
        runner_text = RUNNER.read_text(encoding="utf-8")

        self.assertIn("origin_plot.py", runner_text)
        self.assertIn("origin_plot_engine.py", runner_text)
        self.assertIn("$runtimeEngine", runner_text)

    def test_local_engine_is_the_origin_embedded_python_entrypoint(self):
        engine_text = ENGINE.read_text(encoding="utf-8")

        self.assertIn("import originpro as op", engine_text)
        self.assertIn('runtime_value("ELECTROCHEM_ORIGIN_JOB"', engine_text)
        self.assertIn("op.save(job[\"project_path\"])", engine_text)


if __name__ == "__main__":
    unittest.main()
