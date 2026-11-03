import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class FullTextLearningPolicyTests(unittest.TestCase):
    def _request(self, maximum=5):
        from electrochem_harness.academic_search import AcademicSearchRequest

        return AcademicSearchRequest(
            domain="卤化物固态电解质",
            research_question="卤化物正极界面稳定性如何影响循环？",
            concept_groups=(("halide electrolyte", "chloride electrolyte"), ("cathode interface", "interface")),
            databases=("crossref", "openalex"),
            max_results=maximum,
        )

    def test_one_learning_run_cannot_request_more_than_five_papers(self):
        with self.assertRaises(ValueError):
            self._request(6)

    def test_selection_keeps_only_high_quality_high_relevance_papers(self):
        from electrochem_harness.learning_policy import select_learning_records

        records = [
            {"doi": "10.1000/good", "title": "Halide electrolyte cathode interface stability", "journal": "Nature Communications", "abstract": "Halide electrolyte cathode interface cycling.", "year": 2025},
            {"doi": "10.1000/weak", "title": "Halide electrolyte cathode interface stability", "journal": "Unverified Local Journal", "abstract": "Halide electrolyte cathode interface cycling.", "year": 2025},
            {"doi": "10.1000/offtopic", "title": "Catalysis in aqueous media", "journal": "Advanced Energy Materials", "abstract": "Water splitting catalyst.", "year": 2025},
        ]
        selected, excluded = select_learning_records(self._request(), records, limit=5)

        self.assertEqual([item["doi"] for item in selected], ["10.1000/good"])
        self.assertEqual(selected[0]["journal_quality_tier"], "B")
        self.assertGreaterEqual(selected[0]["relevance_score"], 65)
        reasons = " ".join(reason for item in excluded for reason in item["reasons"])
        self.assertIn("期刊水平", reasons)
        self.assertIn("相关性", reasons)

    def test_fulltext_binding_rejects_thin_or_unmatched_documents(self):
        from electrochem_harness.fulltext import DocumentEvidence
        from electrochem_harness.learning_policy import bind_fulltext_documents

        records = [{"doi": "10.1000/good", "title": "Halide electrolyte cathode interface stability"}]
        thin = DocumentEvidence(
            source_id="10.1000/good", title="Halide electrolyte cathode interface stability", doi="10.1000/good",
            source_uri="thin.pdf", evidence_level="local_pdf_text", background_excerpt="short", methods_excerpt="",
            figure_table_evidence=(), body_excerpt="abstract only", content_hash="a" * 64, limitations=(),
        )
        matched, excluded = bind_fulltext_documents(records, [thin])

        self.assertEqual(matched, [])
        self.assertTrue(any("原文不足" in reason for item in excluded for reason in item["reasons"]))

    def test_ranked_candidate_pool_can_exceed_five_for_download_backfill(self):
        from electrochem_harness.learning_policy import rank_learning_records, select_learning_records

        records = [
            {
                "doi": "10.1000/good{}".format(index),
                "title": "Halide electrolyte cathode interface stability {}".format(index),
                "journal": "Nature Communications",
                "abstract": "Halide electrolyte cathode interface cycling.",
                "year": 2025,
                "pdf_url": "https://example.org/{}.pdf".format(index),
            }
            for index in range(7)
        ]
        ranked, _ = rank_learning_records(self._request(), records)
        selected, _ = select_learning_records(self._request(), records, limit=5)

        self.assertEqual(len(ranked), 7)
        self.assertEqual(len(selected), 5)

    def test_only_approved_knowledge_is_inherited_by_next_run(self):
        from electrochem_harness.knowledge_assistant import ResearchKnowledgeStore, knowledge_candidate_key

        reasoning = {
            "summary": "候选综合结论",
            "recommended_search_terms": [],
            "article_core_findings": [],
            "research_background": [],
            "electrochemistry_foundations": [],
            "key_figures_tables": [],
            "learning_delta": [],
            "data_value_assessment": [],
            "missing_experiments": [],
            "missing_characterization": [],
            "cannot_determine": [],
            "knowledge_candidates": [
                {"claim": "批准知识", "source_ids": ["10.1000/a"], "conditions": "卤化物", "confidence": "high", "verification_needed": "已核对原文"},
                {"claim": "未批准知识", "source_ids": ["10.1000/b"], "conditions": "卤化物", "confidence": "low", "verification_needed": "待核对"},
            ],
        }
        from electrochem_harness.knowledge_assistant import KnowledgeAssistantRequest
        request = KnowledgeAssistantRequest(search=self._request(), max_documents=5, max_evidence_chars=10000)
        with tempfile.TemporaryDirectory() as temp:
            store = ResearchKnowledgeStore(Path(temp) / "knowledge.md")
            entry = store.update_candidate(request, reasoning, evidence_hash="a" * 64, run_id="run-1", source_ids=("10.1000/a", "10.1000/b"))
            approved_id = knowledge_candidate_key(reasoning["knowledge_candidates"][0])
            store.set_candidate_status(entry, approved_id, "approved", "已核对正文和图表。")
            inherited = store.approved_evidence("卤化物固态电解质")
            learned_sources = store.learned_source_ids("卤化物固态电解质")

        self.assertEqual(len(inherited), 1)
        self.assertEqual(inherited[0]["claim"], "批准知识")
        self.assertEqual(inherited[0]["status"], "approved")
        self.assertEqual(learned_sources, ["10.1000/a", "10.1000/b"])


if __name__ == "__main__":
    unittest.main()
