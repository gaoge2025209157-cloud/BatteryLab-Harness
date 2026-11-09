from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from electrochem_harness_v2.origin_adapter import OriginAdapter
from electrochem_harness_v2.workflow import ResearchWorkflow


class AutomatedWorkflowTests(unittest.TestCase):
    def test_run_all_reports_every_safe_stage_without_manual_buttons(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf = pymupdf.open()
            pdf.new_page().insert_text((72, 72), "A local paper")
            pdf.save(pdf_path)
            pdf.close()
            data_path = root / "data.csv"
            data_path.write_text("time,capacity,voltage\n0,0,3\n1,10,2\n2,0,3\n", encoding="utf-8")
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            workflow.origin_adapter = OriginAdapter(root / "missing.ps1", runner=lambda *_: None)
            workflow.search_literature = lambda _project, _keywords: type("Search", (), {"status": "LITERATURE_SEARCHED"})()
            project_id = workflow.create_project("Test", "P2O5|LiTaCl6", ["P2O5"])
            events = []
            result = workflow.run_all(
                project_id, data_path, {"temperature_C": 60}, pdf_path=pdf_path,
                keywords=["P2O5"], use_codex_candidates=False, use_codex_assessment=False, use_online_research=False,
                progress=lambda stage, message, details: events.append((stage, message, details)),
            )
            self.assertTrue(result["report"].is_file())
            self.assertIn("SEARCH", [item[0] for item in events])
            self.assertIn("PDF", [item[0] for item in events])
            self.assertIn("DATA", [item[0] for item in events])
            self.assertIn("ORIGIN", [item[0] for item in events])
            self.assertIn("REPORT", [item[0] for item in events])
            self.assertEqual(result["run"].project_id, project_id)
            manifest = json.loads((result["run"].output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["origin_status"], "PLOT_BLOCKED")


if __name__ == "__main__":
    unittest.main()
