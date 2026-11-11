from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import electrochem_harness_v2


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_package_and_project_versions_match(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(electrochem_harness_v2.__version__, config["project"]["version"])
        self.assertEqual(config["build-system"]["build-backend"], "setuptools.build_meta")
        self.assertEqual(config["tool"]["setuptools"]["packages"]["find"]["where"], ["src"])

    def test_windows_launch_requires_the_local_environment(self):
        start = (ROOT / "start_gui.cmd").read_text(encoding="utf-8")
        setup = (ROOT / "setup_env.cmd").read_text(encoding="utf-8")
        self.assertIn('.venv\\Scripts\\python.exe', start)
        self.assertIn("Run setup_env.cmd first", start)
        self.assertIn('-m pip install -e "."', setup)


if __name__ == "__main__":
    unittest.main()
