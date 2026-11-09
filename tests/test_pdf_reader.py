from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from electrochem_harness_v2.pdf_reader import LocalPdfReader


class LocalPdfReaderTests(unittest.TestCase):
    def test_reads_each_page_with_stable_spans_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "paper.pdf"
            document = fitz.open()
            first = document.new_page()
            first.insert_text((72, 72), "Test paper\nFig. 1 Conductivity result\nDOI 10.1000/test")
            second = document.new_page()
            second.insert_text((72, 72), "Methods\nThe cell was tested at 60 C.")
            document.save(pdf_path)
            document.close()

            result = LocalPdfReader().read(pdf_path)

        self.assertEqual(result.document.page_count, 2)
        self.assertEqual(result.document.extraction_status, "complete")
        self.assertEqual(result.document.coverage_manifest["text_pages"], [1, 2])
        self.assertEqual({span.page_index for span in result.spans}, {1, 2})
        self.assertTrue(any("Fig. 1" in span.figure_ids for span in result.spans))
        self.assertTrue(result.document.sha256)

    def test_rejects_non_pdf_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-pdf.txt"
            path.write_text("not a PDF", encoding="utf-8")
            with self.assertRaises(ValueError):
                LocalPdfReader().read(path)


if __name__ == "__main__":
    unittest.main()
