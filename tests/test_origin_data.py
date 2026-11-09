from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.csv_importer import GcdCsvImporter
from electrochem_harness_v2.origin_data import prepare_origin_tables


class OriginDataTests(unittest.TestCase):
    def test_prepares_tables_without_rewriting_source_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            source.write_text("time,capacity,voltage\n0,0,2\n1,10,3\n2,0,3\n3,8,2\n4,0,2\n", encoding="utf-8")
            imported = GcdCsvImporter().read(source)
            outputs = prepare_origin_tables(imported, root / "origin")
            self.assertTrue(outputs["curves"].is_file())
            self.assertTrue(outputs["summary"].is_file())
            curves = outputs["curves"].read_text(encoding="utf-8-sig")
            summary = outputs["summary"].read_text(encoding="utf-8-sig")
            self.assertIn("cycle,direction,specific_capacity_mAh_g,voltage_V", curves)
            self.assertIn("1,charge,10.0,3.0", curves)
            self.assertIn("1,discharge,8.0,2.0", curves)
            self.assertIn("cycle,charge_specific_capacity_mAh_g,discharge_specific_capacity_mAh_g,coulombic_efficiency_percent,complete", summary)
            self.assertIn("1,10.0,8.0,80.0,true", summary)
            self.assertEqual(source.read_text(encoding="utf-8").splitlines()[0], "time,capacity,voltage")


if __name__ == "__main__":
    unittest.main()
