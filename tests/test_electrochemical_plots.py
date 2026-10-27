import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class ElectrochemicalPlotCatalogTests(unittest.TestCase):
    def test_catalog_covers_eleven_literature_plot_families(self):
        from electrochem_harness.electrochemical_plots import PLOT_SPECS

        expected = {
            "charge_discharge",
            "cycling_efficiency",
            "rate_capability",
            "dqdv",
            "cv_lsv",
            "eis_nyquist",
            "eis_bode",
            "gitt_pitt",
            "arrhenius",
            "dc_polarization",
            "ccd",
        }
        self.assertEqual(set(PLOT_SPECS), expected)
        for spec in PLOT_SPECS.values():
            self.assertTrue(spec.required_columns)
            self.assertTrue(spec.scientific_question)
            self.assertTrue(spec.reference_dois)

    def test_every_plot_family_accepts_its_canonical_csv_and_writes_nature_svg(self):
        from electrochem_harness.electrochemical_plots import create_electrochemical_plot

        fixtures = {
            "charge_discharge": (
                ["cycle", "direction", "specific_capacity_mAh_g", "voltage_V"],
                [[1, "charge", 0, 2.0], [1, "charge", 100, 3.0], [1, "discharge", 0, 3.0], [1, "discharge", 90, 2.0]],
            ),
            "cycling_efficiency": (
                ["cycle", "charge_specific_capacity_mAh_g", "discharge_specific_capacity_mAh_g", "coulombic_efficiency_percent"],
                [[1, 100, 90, 90], [2, 95, 88, 92.6]],
            ),
            "rate_capability": (
                ["cycle", "rate_C", "discharge_specific_capacity_mAh_g"],
                [[1, 0.1, 100], [2, 0.2, 90], [3, 0.5, 75]],
            ),
            "dqdv": (
                ["voltage_V", "dQ_dV_mAh_g_V"],
                [[2.0, 10], [2.5, 25], [3.0, 5]],
            ),
            "cv_lsv": (
                ["scan", "potential_V", "current_mA"],
                [[1, 0.0, 0.0], [1, 1.0, 0.2], [1, 2.0, -0.1]],
            ),
            "eis_nyquist": (
                ["frequency_Hz", "z_real_ohm", "z_imag_ohm"],
                [[100000, 5, -1], [1000, 10, -5], [10, 20, -2]],
            ),
            "eis_bode": (
                ["frequency_Hz", "z_magnitude_ohm", "phase_degree"],
                [[10, 100, -70], [1000, 20, -30], [100000, 5, -5]],
            ),
            "gitt_pitt": (
                ["time_s", "voltage_V"],
                [[0, 2.0], [100, 2.2], [200, 2.1]],
            ),
            "arrhenius": (
                ["temperature_C", "conductivity_S_cm"],
                [[25, 0.001], [40, 0.002], [60, 0.004]],
            ),
            "dc_polarization": (
                ["time_s", "current_mA"],
                [[0, 1.0], [100, 0.2], [200, 0.1]],
            ),
            "ccd": (
                ["time_h", "voltage_V", "current_density_mA_cm2"],
                [[0, 0.01, 0.1], [1, -0.01, -0.1], [2, 0.02, 0.2]],
            ),
        }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for plot_type, (headers, rows) in fixtures.items():
                with self.subTest(plot_type=plot_type):
                    source = root / (plot_type + ".csv")
                    with source.open("w", encoding="utf-8-sig", newline="") as handle:
                        writer = csv.writer(handle)
                        writer.writerow(headers)
                        writer.writerows(rows)
                    result = create_electrochemical_plot(plot_type, source, root / "out")
                    svg = result.svg_path.read_text(encoding="utf-8")
                    audit = json.loads(result.audit_path.read_text(encoding="utf-8"))
                    self.assertIn("font-family=\"Arial", svg)
                    self.assertIn("#E64B35", svg)
                    self.assertNotRegex(svg.casefold(), r"(?<![a-z])nan(?![a-z])")
                    self.assertEqual(audit["plot_type"], plot_type)
                    self.assertTrue(audit["source_sha256"])

    def test_si_unit_headers_are_normalized_without_user_unit_options(self):
        from electrochem_harness.electrochemical_plots import load_plot_table

        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "polarization.csv"
            source.write_text(
                "Time(min),Current(A)\n0,0.001\n1,0.0002\n",
                encoding="utf-8",
            )
            table = load_plot_table(source)

        self.assertAlmostEqual(table.rows[1]["time_s"], 60.0)
        self.assertAlmostEqual(table.rows[0]["current_mA"], 1.0)


class GuiScientificUnitTests(unittest.TestCase):
    def test_gui_uses_fixed_ma_and_celsius_and_has_no_normalization_choice(self):
        from electrochem_harness.gui_controller import METADATA_FIELDS

        fields = {name: (label, hint) for name, label, hint in METADATA_FIELDS}
        self.assertNotIn("normalization_basis", fields)
        self.assertEqual(fields["test_current"][1], "mA")
        self.assertEqual(fields["temperature"][1], "°C")


class NatureOriginThemeTests(unittest.TestCase):
    def test_origin_uses_one_nature_theme_configuration(self):
        source = (PROJECT_ROOT / "origin_plot.py").read_text(encoding="utf-8")
        self.assertIn("NATURE_COLORS", source)
        self.assertIn("font(Arial)", source)
        self.assertIn("AXIS_STROKE_PT", source)
        self.assertNotIn("layer.x.thickness=4", source)


if __name__ == "__main__":
    unittest.main()
