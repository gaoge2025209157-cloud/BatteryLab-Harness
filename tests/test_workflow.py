from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from electrochem_harness_v2.workflow import ResearchWorkflow


class ResearchWorkflowTests(unittest.TestCase):
    def test_local_pdf_and_csv_create_a_recoverable_needs_review_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf = pymupdf.open()
            page = pdf.new_page()
            page.insert_text((72, 72), "A test paper\nFig. 1 A test figure")
            pdf.save(pdf_path)
            pdf.close()
            csv_path = root / "data.csv"
            csv_path.write_text("time,capacity,voltage\n0,0,3\n1,20,2\n2,0,3\n", encoding="utf-8")
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            project_id = workflow.create_project("Test", "P2O5|LiTaCl6|Li-In", ["P2O5"])
            source = workflow.learn_local_pdf(project_id, pdf_path)
            run = workflow.analyze_data(project_id, csv_path, {"temperature_C": 60})
            report = workflow.build_report(project_id, run.run_id)

            self.assertEqual(source.extraction_status, "complete")
            self.assertEqual(run.status, "NEEDS_REVIEW")
            self.assertTrue(report.is_file())
            html = report.read_text(encoding="utf-8")
            self.assertIn("一、课题背景与研究问题", html)
            self.assertIn("五、综合结论与下一步实验", html)
            self.assertIn("Test", html)

    def test_builds_research_context_with_project_details_and_bounded_features(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            project_id = workflow.create_project("LPSC 固态电池", "P2O5|LPSC|Li-In", ["P2O5", "LPSC", "Li-In"])
            analysis = {
                "metadata": {"source_name": "data.csv"},
                "analysis": {
                    "row_count": 240000,
                    "rows": [{"voltage": 1.2}],
                    "gcd_summary": {"latest_capacity_retention_percent": 97.9},
                    "cycles": [{"cycle": 1, "discharge_specific_capacity_mAh_g": 1100}],
                },
            }
            context = workflow._build_research_context(project_id, {"temperature_C": 60}, analysis)
        self.assertEqual(context["project_name"], "LPSC 固态电池")
        self.assertEqual(context["material_system"], "P2O5|LPSC|Li-In")
        self.assertEqual(context["experiment_conditions"]["temperature_C"], 60)
        self.assertEqual(context["deterministic_features"]["row_count"], 240000)
        self.assertNotIn("rows", json.dumps(context, ensure_ascii=False))
