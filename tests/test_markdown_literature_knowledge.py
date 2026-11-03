import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class MarkdownLiteratureKnowledgeTests(unittest.TestCase):
    def _profile(self, material="Li3ScCl6"):
        from electrochem_harness.literature import ResearchProfile

        return ResearchProfile(
            battery_system="halide all-solid-state lithium battery",
            active_material=material,
            cell_type="half cell",
            counter_electrode="Li-In",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="cathode active material mass",
        )

    def _search_result(self):
        return {
            "source": "Crossref REST API",
            "searched_at": "2026-10-15T00:00:00+00:00",
            "records": [
                {
                    "doi": "10.1000/interface",
                    "doi_verified": True,
                    "title": "Interfacial stability in halide solid-state batteries",
                    "journal": "Verified Journal",
                    "year": 2025,
                    "abstract": (
                        "Interfacial resistance controls polarization in the composite cathode. "
                        "The cell delivered 150 mAh g-1 after 100 cycles."
                    ),
                    "metrics": {
                        "specific_capacity_mAh_g": 150.0,
                        "cycle_count": 100.0,
                    },
                    "match_level": "direct",
                    "research_roles": ["benchmark", "background"],
                },
                {
                    "doi": "10.1000/unverified",
                    "doi_verified": False,
                    "title": "Unverified paper",
                    "abstract": "This must never enter the knowledge base.",
                },
            ],
        }

    def test_discovery_metadata_is_not_written_to_markdown_knowledge(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "literature_knowledge.md"
            result = MarkdownLiteratureKnowledgeStore(path).update_from_search(
                self._profile(), self._search_result()
            )

        self.assertFalse(path.exists())
        self.assertEqual(result["stored"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["skipped_discovery_only"], 2)
        self.assertEqual(result["write_policy"], "fulltext_llm_learning_only")

    def test_repeat_discovery_updates_remain_no_op(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "literature_knowledge.md"
            store = MarkdownLiteratureKnowledgeStore(path)
            first = store.update_from_search(self._profile(), self._search_result())
            second = store.update_from_search(self._profile(), self._search_result())

        self.assertFalse(path.exists())
        self.assertEqual(first["stored"], 0)
        self.assertEqual(second["updated"], 0)

    def test_discovery_results_never_become_judgment_basis(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "literature_knowledge.md"
            store = MarkdownLiteratureKnowledgeStore(path)
            store.update_from_search(self._profile(), self._search_result())
            matching = store.summary(self._profile())
            other = store.summary(self._profile(material="Li6PS5Cl"))

        self.assertEqual(matching["approved_record_count"], 0)
        self.assertEqual(matching["candidate_record_count"], 0)
        self.assertEqual(matching["approved_claims"], [])
        self.assertEqual(other["approved_record_count"], 0)

    def test_empty_store_can_be_created_for_manual_editing(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge" / "literature_knowledge.md"
            created = MarkdownLiteratureKnowledgeStore(path).ensure_exists()
            text = path.read_text(encoding="utf-8")

        self.assertEqual(created, path)
        self.assertIn("用户总则（可编辑）", text)

    def test_bundle_does_not_persist_metadata_or_abstract_as_knowledge(self):
        from electrochem_harness.sci_report import create_scientific_bundle

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "curve.csv"
            source.write_text(
                "测试时间/h,比容量/mAh/g,电压/V\n"
                "0.00,0,1.2\n0.01,100,0.5\n0.01,0,0.6\n"
                "0.02,120,2.5\n0.02,0,2.4\n0.03,110,0.5\n",
                encoding="utf-8",
            )
            knowledge_path = root / "knowledge" / "literature_knowledge.md"
            with patch(
                "electrochem_harness.literature.search_crossref",
                return_value=self._search_result(),
            ):
                bundle = create_scientific_bundle(
                    source,
                    root / "output",
                    research_profile=self._profile(),
                    search_literature=True,
                    max_literature=1,
                    literature_markdown_path=knowledge_path,
                )
            payload = json.loads(bundle["json"].read_text(encoding="utf-8"))

        knowledge = payload["editable_literature_knowledge"]
        self.assertFalse(knowledge_path.exists())
        self.assertEqual(knowledge["new_or_updated_record_count"], 0)
        self.assertEqual(knowledge["write_policy"], "fulltext_llm_learning_only")


if __name__ == "__main__":
    unittest.main()
