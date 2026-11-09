from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.csv_importer import GcdCsvImporter


class GcdCsvImporterTests(unittest.TestCase):
    def test_preserves_soc_column_as_auxiliary_not_current(self):
        content = (
            "测试时间/h,比容量/mAh/g,SOC|DOD/%,电压/V\n"
            "0.00,0.0,0,3.0\n"
            "0.00,10.0,10,2.5\n"
            "0.01,20.0,20,-0.1\n"
            "0.02,0.0,0,2.8\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "curve.csv"
            path.write_bytes(content.encode("gb18030"))
            result = GcdCsvImporter().read(path)

        self.assertEqual(result.metadata.mode, "specific_capacity_curve")
        self.assertEqual(result.metadata.encoding, "gb18030")
        self.assertEqual(result.metadata.column_mapping["auxiliary"], "SOC|DOD/%")
        self.assertNotIn("current", result.metadata.column_mapping)
        self.assertEqual(result.analysis["row_count"], 4)
        self.assertEqual(result.analysis["negative_voltage_count"], 1)
        self.assertEqual(result.analysis["repeated_or_reversed_time_pairs"], 1)
        self.assertEqual(len(result.analysis["segments"]), 2)

    def test_rejects_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("time,capacity,voltage\n0,0,3\n1,NaN,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                GcdCsvImporter().read(path)


if __name__ == "__main__":
    unittest.main()
