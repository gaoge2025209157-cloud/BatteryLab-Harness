from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.report import write_report


class ReportConclusionTests(unittest.TestCase):
    def test_reports_user_supplied_li_s_capacity_potential_and_hides_unverified_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(
                path,
                {"status": "REPORT_READY_WITH_NO_COMPARABLE_PAPERS"},
                [],
                [],
                guidance={
                    "assessment": "The first complete discharge capacity is higher than the user-specified Li-S theoretical reference.",
                    "data_facts": ["First complete discharge capacity: 3627.9 mAh/g."],
                    "cannot_determine": ["Full-cell energy density."],
                    "hypotheses": [],
                    "benchmark_comparisons": [{"metric": "capacity", "observed": "3627.9 mAh/g", "reference": "1675 mAh/g", "comparability": "context_only", "conclusion": "Potential by active-material capacity", "evidence_status": "user_provided", "source_urls": []}, {"metric": "bad", "observed": "unknown", "reference": "unknown", "comparability": "candidate", "conclusion": "Do not show", "evidence_status": "candidate", "source_urls": []}],
                    "theoretical_energy_assessment": {"conclusion": "Candidate only"},
                    "next_experiments": [],
                },
                analysis={"gcd_summary": {"first_complete_discharge_capacity_mAh_g": 3627.9}},
                benchmark={"codex_web_research": {"mainstream_systems": [{"system": "NMC", "specific_capacity_mAh_g": None, "source_urls": ["https://example.org"]}], "standards": [{"name": "Candidate", "issuer": "X", "scope": "Y", "url": "https://example.org"}]}},
            )
            html = path.read_text(encoding="utf-8")
        self.assertIn("1675 mAh g⁻¹", html)
        self.assertIn("Li–S", html)
        self.assertNotIn("Do not show", html)
        self.assertNotIn("标准/规范", html)
        self.assertIn("网页候选的性能数值不直接写入本课题结论", html)

    def test_reports_literature_tests_and_borrowable_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(path, {"status": "REPORT_READY"}, [], [], guidance={
                "assessment": "assessment", "data_facts": [], "cannot_determine": [], "hypotheses": [], "benchmark_comparisons": [], "theoretical_energy_assessment": {"conclusion": "x"}, "next_experiments": [],
            }, benchmark={"research_synthesis": {"search_question": "What limits the interface?", "data_literature_connection": "The high polarization requires interface diagnosis.", "evidence_boundaries": ["Candidate sources need review."]}, "literature_studies": [{"study": "Interface stability", "tests": ["XPS", "EIS"], "question": "What fails?", "finding": "Interphase growth", "how_to_borrow": "Add XPS after cycling", "source_urls": ["https://example.org/paper"], "evidence_status": "web_search_candidate"}]})
            html = path.read_text(encoding="utf-8")
        self.assertIn("四、Codex 联网文献学习明细", html)
        self.assertIn("XPS", html)
        self.assertIn("Add XPS after cycling", html)
        self.assertIn("The high polarization requires interface diagnosis.", html)
        self.assertIn("文献学习结果", html)
    def test_reports_user_confirmed_p2o5_reaction_energy_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.html"
            write_report(path, {"material_system": "P2O5|LPSC", "conditions": {}}, [], [], analysis={"gcd_summary": {"first_complete_average_discharge_voltage_V": 1.5}})
            html = path.read_text(encoding="utf-8")
        self.assertIn("P₂O₅ + 16Li → 5Li₂O + 2Li₃P", html)
        self.assertIn("3021", html)
        self.assertIn("4531", html)


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
                benchmark={"codex_activity": [{"stage": "CODEX_ASSESSMENT", "status": "FAILED", "message": "failed", "details": {"error": "stream disconnected"}}]},
            )
            html = path.read_text(encoding="utf-8")
        self.assertIn("基于确定性数据的综合判断", html)
        self.assertIn("容量保持率为 48.80%", html)
        self.assertIn("结合仪器步骤核对循环分段", html)
        self.assertNotIn("Codex 尚未形成通过结构校验的本轮评价", html)


if __name__ == "__main__":
    unittest.main()
