import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class LiteratureKnowledgeStoreTests(unittest.TestCase):
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
                    "metrics": {"specific_capacity_mAh_g": 150.0, "cycle_count": 100.0},
                    "match_level": "direct",
                    "research_roles": ["benchmark", "background"],
                    "condition_matches": {"active_material": True},
                },
                {
                    "doi": "10.1000/unverified",
                    "doi_verified": False,
                    "title": "Unverified claim",
                    "metrics": {},
                },
            ],
        }

    def test_store_keeps_only_verified_doi_and_deduplicates_repeated_searches(self):
        from electrochem_harness.literature_knowledge import LiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            store = LiteratureKnowledgeStore(Path(tmp) / "literature.jsonl")
            first = store.update_from_search(self._profile(), self._search_result())
            second = store.update_from_search(self._profile(), self._search_result())
            records = store.find(self._profile())

        self.assertEqual(first["stored"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["doi"], "10.1000/interface")
        self.assertEqual(records[0]["times_seen"], 2)
        self.assertNotIn("10.1000/unverified", json.dumps(records))

    def test_store_is_scoped_by_complete_research_profile(self):
        from electrochem_harness.literature_knowledge import LiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            store = LiteratureKnowledgeStore(Path(tmp) / "literature.jsonl")
            store.update_from_search(self._profile(), self._search_result())
            same = store.find(self._profile())
            other = store.find(self._profile(material="Li6PS5Cl"))

        self.assertEqual(len(same), 1)
        self.assertEqual(other, [])

    def test_mechanism_sentences_are_stored_as_candidates_not_facts(self):
        from electrochem_harness.literature_knowledge import LiteratureKnowledgeStore

        with tempfile.TemporaryDirectory() as tmp:
            store = LiteratureKnowledgeStore(Path(tmp) / "literature.jsonl")
            store.update_from_search(self._profile(), self._search_result())
            record = store.find(self._profile())[0]

        self.assertEqual(record["candidate_claims"][0]["status"], "candidate")
        self.assertIn("Interfacial resistance", record["candidate_claims"][0]["text"])
        self.assertEqual(record["candidate_claims"][0]["source_doi"], "10.1000/interface")


class BackgroundSearchTests(unittest.TestCase):
    def test_crossref_runs_benchmark_and_background_queries_and_tags_roles(self):
        from electrochem_harness.literature import ResearchProfile, search_crossref

        profile = ResearchProfile(
            battery_system="solid state lithium battery",
            active_material="Li3ScCl6",
            cell_type="half cell",
            counter_electrode="Li-In",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="active material mass",
        )
        item = {
            "DOI": "10.1000/review",
            "title": ["Interface mechanisms in solid state lithium batteries"],
            "container-title": ["Verified Journal"],
            "type": "journal-article",
            "abstract": "Li3ScCl6 interface kinetics and degradation mechanisms are reviewed.",
        }
        search_urls = []

        def fake_fetch(url):
            if "/works?" in url:
                search_urls.append(url)
                return {"message": {"items": [item]}}
            return {"message": item}

        result = search_crossref(profile, max_results=5, fetch_json=fake_fetch)

        self.assertEqual(len(search_urls), 2)
        self.assertTrue(any("mechanism" in url or "review" in url for url in search_urls))
        self.assertIn("benchmark", result["records"][0]["research_roles"])
        self.assertIn("background", result["records"][0]["research_roles"])


class OpenAlexEnrichmentTests(unittest.TestCase):
    def test_reconstructs_openalex_abstract_in_reading_order(self):
        from electrochem_harness.literature import _abstract_from_inverted_index

        abstract = _abstract_from_inverted_index(
            {
                "Interface": [0],
                "resistance": [1],
                "controls": [2],
                "polarization.": [3],
            }
        )

        self.assertEqual(abstract, "Interface resistance controls polarization.")


class DoctoralReportTests(unittest.TestCase):
    def test_report_contains_mathematical_basis_and_knowledge_reuse_summary(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import render_concise_markdown

        profile = ResearchProfile(
            battery_system="halide solid-state battery",
            active_material="Li3ScCl6",
            cell_type="half cell",
            counter_electrode="Li-In",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="active material mass",
        )
        payload = {
            "report": {
                "status": "ok",
                "initial_discharge_capacity_mAh_g": None,
                "cycles": [{
                    "cycle": 1,
                    "charge_specific_capacity_mAh_g": 100.0,
                    "discharge_specific_capacity_mAh_g": 90.0,
                    "coulombic_efficiency": 0.9,
                    "capacity_retention": 1.0,
                    "average_charge_voltage_V": 2.5,
                    "average_discharge_voltage_V": 2.0,
                    "charge_plateau_voltage_V": 2.4,
                    "discharge_plateau_voltage_V": 2.1,
                    "complete": True,
                }],
                "quality_issues": [],
            },
            "literature_knowledge": {
                "reused_record_count": 3,
                "new_or_updated_record_count": 1,
                "candidate_claim_count": 2,
            },
        }

        text = render_concise_markdown(
            payload, None, None, None, None,
            research_profile=profile,
            literature_result=None,
        )

        self.assertIn("## 数学与物理化学分析依据", text)
        self.assertIn("Q =", text)
        self.assertIn("CE =", text)
        self.assertIn("不能仅由恒流循环曲线反演", text)
        self.assertIn("复用 3 条", text)

    def test_bundle_persists_verified_search_results_to_requested_knowledge_path(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import create_scientific_bundle

        profile = ResearchProfile(
            battery_system="halide solid-state battery",
            active_material="Li3ScCl6",
            cell_type="half cell",
            counter_electrode="Li-In",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="active material mass",
        )
        literature = {
            "source": "Crossref REST API",
            "candidate_count": 1,
            "verified_count": 1,
            "directly_comparable_count": 1,
            "records": [{
                "doi": "10.1000/stored",
                "doi_verified": True,
                "title": "Verified study",
                "journal": "Verified Journal",
                "year": 2025,
                "abstract": "Interface resistance affects polarization.",
                "metrics": {},
                "match_level": "direct",
                "research_roles": ["benchmark"],
                "condition_matches": {},
            }],
            "limitations": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "curve.csv"
            source.write_text(
                "测试时间/h,比容量/mAh/g,电压/V\n"
                "0.00,0,1.2\n0.01,100,0.5\n0.01,0,0.6\n"
                "0.02,120,2.5\n0.02,0,2.4\n0.03,110,0.5\n",
                encoding="utf-8",
            )
            knowledge_path = root / "knowledge" / "literature.jsonl"
            with patch("electrochem_harness.literature.search_crossref", return_value=literature):
                paths = create_scientific_bundle(
                    source,
                    root / "output",
                    research_profile=profile,
                    search_literature=True,
                    max_literature=1,
                    literature_knowledge_path=knowledge_path,
                )
            stored = knowledge_path.read_text(encoding="utf-8")
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))

        self.assertIn("10.1000/stored", stored)
        self.assertEqual(payload["literature_knowledge"]["reused_record_count"], 1)


if __name__ == "__main__":
    unittest.main()
