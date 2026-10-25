import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class RepresentativeCycleSelectionTests(unittest.TestCase):
    def test_keeps_every_cycle_when_eight_or_fewer(self):
        from electrochem_harness.sci_report import select_representative_cycles

        cycles = [{"cycle": number, "complete": True} for number in (1, 2, 4, 7, 8)]
        selected = select_representative_cycles(cycles)

        self.assertEqual([item["cycle"] for item in selected], [1, 2, 4, 7, 8])

    def test_selects_exactly_eight_evenly_spaced_cycles_including_ends(self):
        from electrochem_harness.sci_report import select_representative_cycles

        cycles = [{"cycle": number, "complete": True} for number in range(1, 101)]
        selected = select_representative_cycles(cycles)
        numbers = [item["cycle"] for item in selected]

        self.assertEqual(len(numbers), 8)
        self.assertEqual(numbers[0], 1)
        self.assertEqual(numbers[-1], 100)
        self.assertEqual(numbers, sorted(set(numbers)))
        self.assertLessEqual(max(b - a for a, b in zip(numbers, numbers[1:])), 16)


class ScientificOutputSpecificationTests(unittest.TestCase):
    def _payload(self):
        return {
            "report": {
                "status": "warning",
                "initial_discharge_capacity_mAh_g": None,
                "cycles": [
                    {
                        "cycle": 1,
                        "charge_specific_capacity_mAh_g": 1000.0,
                        "discharge_specific_capacity_mAh_g": 900.0,
                        "coulombic_efficiency": 0.90,
                        "capacity_retention": 1.0,
                        "average_charge_voltage_V": 2.5,
                        "average_discharge_voltage_V": 1.7,
                        "charge_plateau_voltage_V": 2.4,
                        "discharge_plateau_voltage_V": 1.8,
                        "complete": True,
                    },
                    {
                        "cycle": 10,
                        "charge_specific_capacity_mAh_g": 650.0,
                        "discharge_specific_capacity_mAh_g": 540.0,
                        "coulombic_efficiency": 540.0 / 650.0,
                        "capacity_retention": 0.60,
                        "average_charge_voltage_V": 2.6,
                        "average_discharge_voltage_V": 1.6,
                        "charge_plateau_voltage_V": 2.5,
                        "discharge_plateau_voltage_V": 1.7,
                        "complete": True,
                    },
                ],
                "quality_issues": [
                    {"code": "negative_voltage", "message": "检测到负电压点。"}
                ],
            }
        }

    def test_report_explains_focus_causes_and_next_experiments_without_claiming_causality(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import render_concise_markdown

        profile = ResearchProfile(
            battery_system="halide all-solid-state lithium battery",
            active_material="Li3ScCl6 composite cathode",
            cell_type="half cell",
            counter_electrode="Li-In",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="cathode active material mass",
        )
        literature = {
            "source": "Crossref REST API",
            "candidate_count": 1,
            "verified_count": 1,
            "directly_comparable_count": 1,
            "records": [
                {
                    "title": "Verified solid-state benchmark",
                    "journal": "Journal of Verified Batteries",
                    "year": 2025,
                    "doi": "10.1000/solid-state",

                    "doi_verified": True,
                    "match_level": "direct",
                    "metrics": {
                        "specific_capacity_mAh_g": 800.0,
                        "coulombic_efficiency_percent": 98.0,
                        "capacity_retention_percent": 85.0,
                        "cycle_count": 100.0,
                    },
                }
            ],
        }

        text = render_concise_markdown(
            self._payload(), None, None, None, None,
            research_profile=profile,
            literature_result=literature,
        )

        self.assertIn("## 该体系应重点关注的指标", text)
        self.assertIn("界面阻抗", text)
        self.assertIn("面容量", text)
        self.assertIn("## 性能偏弱的可能原因", text)
        self.assertIn("可能", text)
        self.assertNotIn("证明原因为", text)
        self.assertIn("## 下一步改进建议", text)
        self.assertIn("EIS", text)
        self.assertIn("10.1000/solid-state", text)

    def test_origin_script_uses_capacity_scatter_and_separate_efficiency_style(self):
        source = (PROJECT_ROOT / "origin_plot.py").read_text(encoding="utf-8")

        self.assertGreaterEqual(source.count('type="scatter"'), 2)
        self.assertIn("set_scatter_style(p1", source)
        self.assertIn("set_scatter_style(p2", source)
        self.assertIn("set_efficiency_style(p3", source)
        self.assertIn("legend_group", source)


class ReadableDecisionSummaryTests(unittest.TestCase):
    def test_summary_is_plain_text_concise_and_cites_basis_with_doi(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import render_readable_summary

        payload = {
            "report": {
                "status": "ok",
                "cycles": [{
                    "cycle": 1,
                    "charge_specific_capacity_mAh_g": 1000.0,
                    "discharge_specific_capacity_mAh_g": 900.0,
                    "coulombic_efficiency": 0.90,
                    "capacity_retention": 1.0,
                    "average_charge_voltage_V": 2.5,
                    "average_discharge_voltage_V": 1.7,
                    "complete": True,
                }],
                "quality_issues": [],
            }
        }
        profile = ResearchProfile(
            battery_system="halide solid-state battery",
            active_material="Li3ScCl6 composite cathode",
            cell_type="half cell",
            counter_electrode="Li-In",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="active material mass",
        )
        literature = {
            "records": [{
                "title": "Verified interface benchmark",
                "doi": "10.1000/interface",
                "doi_verified": True,
                "match_level": "direct",
                "metrics": {"specific_capacity_mAh_g": 800.0},
            }]
        }
        text = render_readable_summary(payload, profile, literature)

        for heading in ("关键指标", "简要结论与科学依据", "实验数据能说明什么", "下一步怎么做"):
            self.assertIn(heading, text)
        self.assertIn("依据：", text)
        self.assertIn("参考文献：", text)
        self.assertIn("10.1000/interface", text)
        self.assertNotIn("**", text)
        self.assertNotIn("##", text)
        self.assertLessEqual(len(text.splitlines()), 28)


if __name__ == "__main__":
    unittest.main()
