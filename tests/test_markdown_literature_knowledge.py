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

    def test_verified_literature_is_summarized_to_editable_markdown(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "literature_knowledge.md"
            store = MarkdownLiteratureKnowledgeStore(path)
            result = store.update_from_search(self._profile(), self._search_result())
            text = path.read_text(encoding="utf-8")

        self.assertEqual(result["stored"], 1)
        self.assertIn("# 电化学文献知识库", text)
        self.assertIn("10.1000/interface", text)
        self.assertIn("Interfacial resistance controls polarization", text)
        self.assertIn("150.0 mAh/g", text)
        self.assertIn("状态：candidate", text)
        self.assertIn("人工确认知识（可编辑）", text)
        self.assertNotIn("10.1000/unverified", text)

    def test_repeat_update_deduplicates_and_preserves_human_edits(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "literature_knowledge.md"
            store = MarkdownLiteratureKnowledgeStore(path)
            store.update_from_search(self._profile(), self._search_result())
            text = path.read_text(encoding="utf-8")
            text = text.replace("状态：candidate", "状态：approved")
            text = text.replace(
                "- （在此填写经你核对后确认的知识；每条一行）",
                "- 界面阻抗增长会提高该体系的极化；应用前需核对阻抗测试条件。",
            )
            text = text.replace(
                "- （可记录页码、图号、条件差异、反例或你的判断）",
                "- 已人工核对论文正文第5页。",
            )
            path.write_text(text, encoding="utf-8")

            result = store.update_from_search(self._profile(), self._search_result())
            updated = path.read_text(encoding="utf-8")

        self.assertEqual(result["updated"], 1)
        self.assertEqual(updated.count("<!-- LITERATURE-ENTRY:START"), 1)
        self.assertIn("状态：approved", updated)
        self.assertIn("界面阻抗增长会提高该体系的极化", updated)
        self.assertIn("已人工核对论文正文第5页", updated)

    def test_only_approved_matching_entries_become_judgment_basis(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "literature_knowledge.md"
            store = MarkdownLiteratureKnowledgeStore(path)
            store.update_from_search(self._profile(), self._search_result())
            text = path.read_text(encoding="utf-8").replace(
                "状态：candidate", "状态：approved"
            ).replace(
                "- （在此填写经你核对后确认的知识；每条一行）",
                "- 已确认：该体系需重点关注界面阻抗与堆叠压力。",
            )
            path.write_text(text, encoding="utf-8")

            matching = store.summary(self._profile())
            other = store.summary(self._profile(material="Li6PS5Cl"))

        self.assertEqual(matching["approved_record_count"], 1)
        self.assertIn("界面阻抗与堆叠压力", matching["approved_claims"][0]["text"])
        self.assertEqual(other["approved_record_count"], 0)
        self.assertEqual(other["approved_claims"], [])

    def test_empty_store_can_be_created_for_manual_editing(self):
        from electrochem_harness.markdown_knowledge import MarkdownLiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "knowledge" / "literature_knowledge.md"
            created = MarkdownLiteratureKnowledgeStore(path).ensure_exists()
            text = path.read_text(encoding="utf-8")

        self.assertEqual(created, path)
        self.assertIn("用户总则（可编辑）", text)

    def test_bundle_updates_markdown_and_records_adopted_knowledge(self):
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
                first = create_scientific_bundle(
                    source,
                    root / "output-1",
                    research_profile=self._profile(),
                    search_literature=True,
                    max_literature=1,
                    literature_markdown_path=knowledge_path,
                )
            text = knowledge_path.read_text(encoding="utf-8").replace(
                "状态：candidate", "状态：approved"
            ).replace(
                "- （在此填写经你核对后确认的知识；每条一行）",
                "- 已确认：界面稳定性是该体系循环性能的重要约束。",
            )
            knowledge_path.write_text(text, encoding="utf-8")

            second = create_scientific_bundle(
                source,
                root / "output-2",
                research_profile=self._profile(),
                search_literature=False,
                literature_markdown_path=knowledge_path,
            )
            payload = json.loads(second["json"].read_text(encoding="utf-8"))
            report = second["report"].read_text(encoding="utf-8")

        self.assertEqual(payload["editable_literature_knowledge"]["approved_record_count"], 1)
        self.assertIn("界面稳定性是该体系循环性能的重要约束", report)
        self.assertEqual(first["knowledge_markdown"], knowledge_path)


if __name__ == "__main__":
    unittest.main()
