import json
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class PaperLibraryTests(unittest.TestCase):
    def _record(self, doi="10.1000/example"):
        return {
            "doi": doi,
            "title": "High quality halide electrolyte interface study",
            "journal": "Nature Communications",
            "year": 2026,
            "landing_url": "https://doi.org/{}".format(doi),
            "pdf_url": "https://example.org/paper.pdf",
            "pdf_urls": ["https://example.org/paper.pdf"],
        }

    def test_download_is_indexed_by_doi_and_second_run_uses_cache(self):
        from electrochem_harness.paper_library import PaperLibrary

        calls = []

        def download(url):
            calls.append(url)
            return b"%PDF-1.7\ncontrolled test pdf\n%%EOF"

        with tempfile.TemporaryDirectory() as temp:
            library = PaperLibrary(Path(temp) / "papers")
            first = library.acquire([self._record()], downloader=download)
            second = library.acquire([self._record()], downloader=download)
            index = json.loads(library.index_path.read_text(encoding="utf-8"))

        self.assertEqual(first[0].status, "downloaded")
        self.assertEqual(second[0].status, "cached")
        self.assertEqual(len(calls), 1)
        self.assertIn("10.1000/example", index["papers"])
        self.assertTrue(second[0].detail.startswith("已存在"))

    def test_paper_without_direct_pdf_is_visible_but_not_fabricated(self):
        from electrochem_harness.paper_library import PaperLibrary

        record = self._record()
        record["pdf_url"] = ""
        record["pdf_urls"] = []
        with tempfile.TemporaryDirectory() as temp:
            result = PaperLibrary(Path(temp) / "papers").acquire([record])

        self.assertEqual(result[0].status, "unavailable")
        self.assertIn("校园网", result[0].detail)
        self.assertEqual(result[0].local_path, "")

    def test_repository_landing_page_can_supply_legal_pdf_fallback(self):
        from unittest.mock import patch
        from electrochem_harness.paper_library import PaperLibrary

        record = self._record()
        record["pdf_url"] = ""
        record["pdf_urls"] = []
        record["fulltext_landing_urls"] = ["https://repository.example/item/1"]
        calls = []

        def download(url):
            calls.append(url)
            return b"%PDF-1.7\nrepository copy\n%%EOF"

        with tempfile.TemporaryDirectory() as temp, patch(
            "electrochem_harness.paper_library._discover_repository_pdf_urls",
            return_value=("https://repository.example/item/1/download",),
        ):
            result = PaperLibrary(Path(temp) / "papers").acquire([record], downloader=download)

        self.assertEqual(result[0].status, "downloaded")
        self.assertEqual(calls, ["https://repository.example/item/1/download"])

    def test_invalid_download_is_not_saved_or_indexed(self):
        from electrochem_harness.paper_library import PaperLibrary

        with tempfile.TemporaryDirectory() as temp:
            library = PaperLibrary(Path(temp) / "papers")
            result = library.acquire([self._record()], downloader=lambda url: b"<html>login</html>")

        self.assertEqual(result[0].status, "failed")
        self.assertFalse(library.index_path.exists())


class SearchPdfMetadataTests(unittest.TestCase):
    def test_openalex_collects_pdf_urls_from_all_locations(self):
        from electrochem_harness.academic_search import _openalex_records

        payload = {
            "results": [
                {
                    "doi": "https://doi.org/10.1000/example",
                    "display_name": "Example",
                    "publication_year": 2026,
                    "primary_location": {"source": {"display_name": "Nature Communications"}},
                    "best_oa_location": {"pdf_url": "https://repo.example/best.pdf"},
                    "locations": [
                        {"pdf_url": "https://repo.example/best.pdf"},
                        {"pdf_url": "https://publisher.example/article.pdf"},
                    ],
                }
            ]
        }
        record = _openalex_records(payload)[0]

        self.assertEqual(record["pdf_url"], "https://repo.example/best.pdf")
        self.assertEqual(len(record["pdf_urls"]), 2)


class QwenRepairTests(unittest.TestCase):
    def test_invalid_list_field_is_repaired_once_then_strictly_validated(self):
        from electrochem_harness.fulltext import DocumentEvidence
        from electrochem_harness.knowledge_assistant import _validate_or_repair_reasoning
        from electrochem_harness.llm_provider import LLMResult
        from tests.test_research_workbench import KnowledgeReviewTests

        valid = KnowledgeReviewTests()._reasoning()
        invalid = dict(valid)
        invalid["research_background"] = "wrong scalar field"
        documents = [
            DocumentEvidence(
                source_id=doi,
                title=doi,
                doi=doi,
                source_uri=doi + ".pdf",
                evidence_level="local_pdf_text",
                background_excerpt="background",
                methods_excerpt="methods",
                figure_table_evidence=("Figure",),
                body_excerpt="body",
                content_hash=("a" if index == 0 else "b") * 64,
                limitations=(),
            )
            for index, doi in enumerate(("10.1000/a", "10.1000/b"))
        ]

        class Provider:
            def __init__(self):
                self.calls = 0

            def generate_json(self, system, payload):
                self.calls += 1
                return LLMResult(valid, "qwen", total_tokens=9)

        provider = Provider()
        result, repaired = _validate_or_repair_reasoning(provider, invalid, documents)

        self.assertEqual(provider.calls, 1)
        self.assertIsNotNone(repaired)
        self.assertIsInstance(result["research_background"], list)


class LiteratureVisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_six_step_dialog_has_live_and_final_five_paper_tables(self):
        from electrochem_harness.gui_six_step import SixStepDialog

        dialog = SixStepDialog(self.root, PROJECT_ROOT)
        dialog.withdraw()
        try:
            papers = [
                {
                    "title": "Paper {}".format(index),
                    "journal": "Nature Communications",
                    "year": 2026,
                    "doi": "10.1000/{}".format(index),
                    "status": "本轮已下载PDF",
                }
                for index in range(5)
            ]
            dialog._render_papers(papers)
            self.assertEqual(len(dialog.paper_tree.get_children()), 5)
            self.assertEqual(len(dialog.result_paper_tree.get_children()), 5)
            self.assertEqual(dialog.result_paper_tree.item("paper-0", "text"), "Paper 0")
        finally:
            dialog.destroy()


if __name__ == "__main__":
    unittest.main()
