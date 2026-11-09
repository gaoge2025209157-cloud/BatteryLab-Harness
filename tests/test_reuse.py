from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf

from electrochem_harness_v2.workflow import ResearchWorkflow


class ReuseTests(unittest.TestCase):
    def test_same_pdf_hash_is_reused_without_second_page_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "paper.pdf"
            pdf = pymupdf.open()
            pdf.new_page().insert_text((72, 72), "Reusable paper")
            pdf.save(pdf_path)
            pdf.close()
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            project_id = workflow.create_project("Test", "P2O5|LiTaCl6", ["P2O5"])
            first = workflow.learn_local_pdf(project_id, pdf_path)
            self.assertTrue(workflow.was_new_source(first.source_id))
            second = workflow.learn_local_pdf(project_id, pdf_path)
            self.assertEqual(first.source_id, second.source_id)
            self.assertFalse(workflow.was_new_source(second.source_id))


if __name__ == "__main__":
    unittest.main()
