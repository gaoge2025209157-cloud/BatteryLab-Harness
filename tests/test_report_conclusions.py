from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.comparison import compare_metric
from electrochem_harness_v2.models import KnowledgeClaim
from electrochem_harness_v2.report import write_report


CONDITIONS = {
    "cathode": "NCM88",
    "electrolyte": "LiCl",
    "temperature_C": 60,
    "normalization_basis": "cathode active mass",
}


def approved_capacity_claim(unit: str = "mAh/g", conditions=None) -> KnowledgeClaim:
    return KnowledgeClaim.new(
        project_id="project-1",
        source_id="source-1",
        claim_type="performance",
        text="Approved reference capacity",
        metric_id="latest_complete_discharge_capacity_mAh_g",
        value=100.0,
        unit=unit,
        conditions=CONDITIONS if conditions is None else conditions,
        evidence_span_ids=["span-1"],
        status="approved",
    )


class ReportConclusionTests(unittest.TestCase):
    def test_approved_matching_claim_is_compared_from_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"project_name": "Generic cathode", "material_system": "NCM88|LiCl", "conditions": CONDITIONS},
                [approved_capacity_claim()],
                [],
                analysis={"gcd_summary": {"latest_complete_discharge_capacity_mAh_g": 110.0}},
            )
            html = path.read_text(encoding="utf-8")
        self.assertIn("Approved reference capacity", html)
        self.assertIn("高于已批准参考值", html)
        self.assertIn("110.000 mAh/g", html)
        self.assertIn("100.000 mAh/g", html)

    def test_ambiguous_capacity_metric_is_not_auto_compared(self):
        claim = KnowledgeClaim.new(
            project_id="project-1",
            source_id="source-1",
            claim_type="performance",
            text="Ambiguous capacity basis",
            metric_id="discharge_specific_capacity_mAh_g",
            value=100.0,
            unit="mAh/g",
            conditions=CONDITIONS,
            status="approved",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"conditions": CONDITIONS},
                [claim],
                [],
                analysis={"gcd_summary": {"latest_complete_discharge_capacity_mAh_g": 110.0}},
            )
            html = path.read_text(encoding="utf-8")
        self.assertIn("Ambiguous capacity basis", html)
        self.assertNotIn("高于已批准参考值", html)

    def test_supplied_deterministic_comparison_is_used(self):
        claim = approved_capacity_claim()
        outcome = compare_metric(
            observed_value=90.0,
            observed_unit="mAh/g",
            observed_conditions=CONDITIONS,
            claim=claim,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(path, {"conditions": CONDITIONS}, [claim], [outcome])
            html = path.read_text(encoding="utf-8")
        self.assertIn("低于已批准参考值", html)
        self.assertIn("90.000 mAh/g", html)

    def test_mismatched_conditions_and_candidate_values_do_not_create_formal_judgment(self):
        claim = approved_capacity_claim(conditions={**CONDITIONS, "temperature_C": 25})
        candidate = KnowledgeClaim.new(
            project_id="project-1",
            source_id="candidate-source",
            claim_type="performance",
            text="Unreviewed candidate value",
            metric_id="discharge_specific_capacity_mAh_g",
            value=50.0,
            unit="mAh/g",
            conditions=CONDITIONS,
            status="candidate",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"conditions": CONDITIONS},
                [claim, candidate],
                [],
                guidance={"assessment": "Candidate result is higher than the web reference."},
                analysis={"gcd_summary": {"latest_complete_discharge_capacity_mAh_g": 110.0}},
                benchmark={"codex_web_research": {"mainstream_systems": [{
                    "system": "Web candidate",
                    "specific_capacity_mAh_g": 50.0,
                    "source_urls": ["https://example.org/paper"],
                }]}},
            )
            html = path.read_text(encoding="utf-8")
        self.assertNotIn("Unreviewed candidate value", html)
        self.assertNotIn("Candidate result is higher", html)
        self.assertNotIn("高于已批准参考值", html)
        self.assertNotIn("低于已批准参考值", html)
        self.assertIn("待审背景，不作优劣判断", html)

    def test_reports_literature_tests_and_borrowable_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"status": "REPORT_READY"},
                [],
                [],
                benchmark={
                    "research_synthesis": {
                        "search_question": "What limits the interface?",
                        "data_literature_connection": "The measured polarization motivates interface checks.",
                        "evidence_boundaries": ["Candidate sources need review."],
                    },
                    "literature_studies": [{
                        "study": "Interface stability",
                        "tests": ["XPS", "EIS"],
                        "question": "What changes?",
                        "finding": "Candidate interphase observation",
                        "how_to_borrow": "Choose characterization after checking composition",
                        "source_urls": ["https://example.org/paper"],
                        "evidence_status": "web_search_candidate",
                    }],
                },
            )
            html = path.read_text(encoding="utf-8")
        self.assertIn("四、文献与知识依据", html)
        self.assertIn("XPS", html)
        self.assertIn("Choose characterization after checking composition", html)
        self.assertIn("文献学习结果", html)

    def test_material_name_does_not_trigger_reaction_or_commercial_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"material_system": "P2O5|LPSC", "conditions": {}},
                [],
                [],
                analysis={"gcd_summary": {"first_complete_average_discharge_voltage_V": 1.5}},
            )
            html = path.read_text(encoding="utf-8")
        for forbidden in ("P₂O₅ + 16Li", "1675", "宁德时代", "麒麟", "LiTaCl₆"):
            self.assertNotIn(forbidden, html)
        self.assertIn("不作定量投影", html)


class ReportFallbackConclusionTests(unittest.TestCase):
    def test_without_codex_guidance_report_shows_deterministic_direction_not_empty_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"status": "CODEX_FAILED"},
                [],
                [],
                analysis={"gcd_summary": {
                    "first_complete_discharge_capacity_mAh_g": 3627.9,
                    "latest_complete_discharge_capacity_mAh_g": 1770.5,
                    "latest_capacity_retention_percent": 48.8,
                    "latest_polarization_voltage_V": 0.572,
                    "latest_coulombic_efficiency_percent": 96.71,
                }},
            )
            html = path.read_text(encoding="utf-8")
        self.assertIn("基于确定性数据的综合判断", html)
        self.assertIn("容量保持率为 48.80%", html)
        self.assertIn("重复电池和单变量实验确认趋势", html)
        self.assertNotIn("Codex 尚未形成通过结构校验的本轮评价", html)


if __name__ == "__main__":
    unittest.main()
