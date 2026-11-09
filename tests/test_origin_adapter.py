from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.origin_adapter import OriginAdapter


class OriginAdapterTests(unittest.TestCase):
    def test_missing_origin_status_is_plot_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            curves = root / "curves.csv"
            summary = root / "summary.csv"
            curves.write_text("cycle,direction,specific_capacity_mAh_g,voltage_V\n", encoding="utf-8")
            summary.write_text("cycle,charge_specific_capacity_mAh_g,discharge_specific_capacity_mAh_g,coulombic_efficiency_percent,complete\n", encoding="utf-8")
            adapter = OriginAdapter(script_path=root / "run_origin.ps1", runner=lambda *_: None)
            result = adapter.plot(root, curves, summary, "run-1", "hash")
            self.assertEqual(result.status, "PLOT_BLOCKED")
            manifest = json.loads((root / "origin" / "origin_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
