import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class ResearchProfileTests(unittest.TestCase):
    def test_profile_names_every_missing_comparison_condition(self):
        from electrochem_harness.literature import ResearchProfile

        profile = ResearchProfile(
            battery_system="锂离子电池",
            active_material="",
            cell_type="半电池",
            counter_electrode="",
            test_current="0.1 C",
            temperature="",
            normalization_basis="",
        )

        self.assertEqual(
            profile.missing_required(),
            ["活性物质", "对电极", "测试温度", "质量归一化口径"],
        )

    def test_guided_questionnaire_collects_all_comparison_fields(self):
        from electrochem_harness.literature import collect_research_profile

        answers = iter([
            "锂硫电池", "S/C 正极", "半电池", "Li", "0.1 C", "25 C", "硫质量"
        ])
        profile = collect_research_profile(
            input_fn=lambda prompt: next(answers), output_fn=lambda message: None
        )

        self.assertEqual(profile.battery_system, "锂硫电池")
        self.assertEqual(profile.active_material, "S/C 正极")
        self.assertEqual(profile.test_current, "0.1 C")
        self.assertEqual(profile.missing_required(), [])

    def test_unknown_placeholders_remain_missing(self):
        from electrochem_harness.literature import ResearchProfile

        profile = ResearchProfile(
            battery_system="待填", active_material="???", cell_type="unknown"
        )

        self.assertIn("电池体系", profile.missing_required())
        self.assertIn("活性物质", profile.missing_required())

    def test_questionnaire_keeps_nonempty_defaults_and_cell_description(self):
        from electrochem_harness.literature import ResearchProfile, collect_research_profile

        defaults = ResearchProfile(
            battery_system="钠离子电池",
            active_material="硬碳",
            cell_type="半电池",
            counter_electrode="Na",
            test_current="100 mA g-1",
            temperature="25 C",
            normalization_basis="活性物质质量",
        )
        profile = collect_research_profile(
            defaults=defaults,
            input_fn=lambda prompt: "",
            output_fn=lambda message: None,
        )

        self.assertEqual(profile.to_dict(), defaults.to_dict())
        self.assertEqual(profile.cell_description, "半电池；对电极：Na")


class CrossrefLiteratureTests(unittest.TestCase):
    def test_search_rechecks_each_doi_and_marks_direct_comparability(self):
        from electrochem_harness.literature import ResearchProfile, search_crossref

        profile = ResearchProfile(
            battery_system="lithium sulfur battery",
            active_material="sulfur carbon cathode",
            cell_type="half cell",
            counter_electrode="lithium metal",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="sulfur mass",
        )
        item = {
            "DOI": "10.1000/test-doi",
            "title": ["Sulfur carbon cathode for lithium sulfur battery half cells"],
            "container-title": ["Journal of Verified Batteries"],
            "published-print": {"date-parts": [[2024]]},
            "author": [{"given": "A.", "family": "Researcher"}],
            "type": "journal-article",
            "is-referenced-by-count": 42,
            "abstract": (
                "Sulfur carbon cathode was evaluated in a lithium sulfur battery half cell "
                "against lithium metal at 0.1 C and 25 C using sulfur mass normalization. "
                "It delivered 1200 mAh g-1 and 98.5% coulombic efficiency."
            ),
        }
        calls = []

        def fake_fetch(url):
            calls.append(unquote(url))
            if "/works?" in url:
                return {"message": {"items": [item]}}
            return {"message": item}

        result = search_crossref(profile, max_results=10, fetch_json=fake_fetch)

        self.assertEqual(result["verified_count"], 1)
        self.assertEqual(result["directly_comparable_count"], 1)
        self.assertTrue(result["records"][0]["doi_verified"])
        self.assertEqual(result["records"][0]["metrics"]["specific_capacity_mAh_g"], 1200.0)
        self.assertTrue(any("10.1000/test-doi" in call for call in calls[1:]))

    def test_unverified_or_non_journal_results_are_not_used_as_benchmarks(self):
        from electrochem_harness.literature import ResearchProfile, search_crossref

        profile = ResearchProfile(
            battery_system="sodium ion battery",
            active_material="hard carbon",
            cell_type="half cell",
            counter_electrode="sodium metal",
            test_current="100 mA g-1",
            temperature="25 C",
            normalization_basis="active material mass",
        )
        search_item = {
            "DOI": "10.1000/unverified",
            "title": ["Hard carbon dataset"],
            "type": "dataset",
        }

        def fake_fetch(url):
            if "/works?" in url:
                return {"message": {"items": [search_item]}}
            raise OSError("DOI lookup failed")

        result = search_crossref(profile, max_results=10, fetch_json=fake_fetch)

        self.assertEqual(result["verified_count"], 0)
        self.assertEqual(result["records"], [])

    def test_incomplete_profile_skips_network_and_reports_missing_conditions(self):
        from electrochem_harness.literature import ResearchProfile, search_crossref

        called = []
        result = search_crossref(
            ResearchProfile(battery_system="锂离子电池"),
            fetch_json=lambda url: called.append(url),
        )

        self.assertEqual(called, [])
        self.assertIn("活性物质", result["missing_conditions"])
        self.assertEqual(result["candidate_count"], 0)

    def test_metric_extraction_is_limited_to_explicit_abstract_values(self):
        from electrochem_harness.literature import extract_reported_metrics

        metrics = extract_reported_metrics(
            "The electrode delivered 321.5 mAh g−1, 99.2% CE, "
            "and 88.0% capacity retention after 500 cycles."
        )

        self.assertEqual(metrics["specific_capacity_mAh_g"], 321.5)
        self.assertEqual(metrics["coulombic_efficiency_percent"], 99.2)
        self.assertEqual(metrics["capacity_retention_percent"], 88.0)
        self.assertEqual(metrics["cycle_count"], 500.0)

    def test_verified_but_condition_incomplete_article_is_background_only(self):
        from electrochem_harness.literature import ResearchProfile, search_crossref

        profile = ResearchProfile(
            battery_system="sodium ion battery",
            active_material="hard carbon",
            cell_type="half cell",
            counter_electrode="sodium metal",
            test_current="100 mA g-1",
            temperature="25 C",
            normalization_basis="active material mass",
        )
        item = {
            "DOI": "10.1000/background",
            "title": ["Hard carbon for sodium ion batteries"],
            "container-title": ["Battery Journal"],
            "published-online": {"date-parts": [[2025, 1, 1]]},
            "type": "journal-article",
        }

        def fake_fetch(url):
            return {"message": {"items": [item]}} if "/works?" in url else {"message": item}

        result = search_crossref(profile, max_results=1, fetch_json=fake_fetch)

        self.assertEqual(result["verified_count"], 1)
        self.assertEqual(result["records"][0]["match_level"], "context_only")
        self.assertEqual(result["directly_comparable_count"], 0)


class LiteratureReportIntegrationTests(unittest.TestCase):
    def _payload(self):
        return {
            "report": {
                "status": "ok",
                "initial_discharge_capacity_mAh_g": None,
                "cycles": [
                    {
                        "cycle": 1,
                        "charge_specific_capacity_mAh_g": 1000.0,
                        "discharge_specific_capacity_mAh_g": 950.0,
                        "coulombic_efficiency": 0.95,
                        "capacity_retention": 1.0,
                        "average_charge_voltage_V": 2.1,
                        "average_discharge_voltage_V": 1.9,
                        "charge_plateau_voltage_V": 2.0,
                        "discharge_plateau_voltage_V": 1.8,
                        "complete": True,
                    }
                ],
                "quality_issues": [],
            }
        }

    def test_report_integrates_verified_benchmark_and_cautious_value_assessment(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import render_concise_markdown

        profile = ResearchProfile(
            battery_system="lithium sulfur battery",
            active_material="sulfur carbon cathode",
            cell_type="half cell",
            counter_electrode="lithium metal",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="sulfur mass",
        )
        literature = {
            "source": "Crossref REST API",
            "searched_at": "2026-10-12T00:00:00Z",
            "verified_count": 1,
            "directly_comparable_count": 1,
            "records": [
                {
                    "title": "Verified benchmark",
                    "journal": "Journal of Verified Batteries",
                    "year": 2024,
                    "doi": "10.1000/test-doi",
                    "doi_verified": True,
                    "citation_count": 42,
                    "match_level": "direct",
                    "metrics": {
                        "specific_capacity_mAh_g": 1200.0,
                        "coulombic_efficiency_percent": 98.5,
                    },
                }
            ],
        }

        text = render_concise_markdown(
            self._payload(),
            material=profile.active_material,
            cell_configuration=profile.cell_description,
            rate=profile.test_current,
            temperature=profile.temperature,
            research_profile=profile,
            literature_result=literature,
        )

        self.assertIn("10.1000/test-doi", text)
        self.assertIn("直接可比文献", text)
        self.assertIn("数据价值判断", text)
        self.assertNotIn("国际领先", text)

    def test_report_refuses_level_claim_when_no_direct_benchmark_exists(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import render_concise_markdown

        profile = ResearchProfile(
            battery_system="lithium sulfur battery",
            active_material="sulfur carbon cathode",
            cell_type="half cell",
            counter_electrode="lithium metal",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="sulfur mass",
        )
        literature = {
            "source": "Crossref REST API",
            "searched_at": "2026-10-12T00:00:00Z",
            "verified_count": 3,
            "directly_comparable_count": 0,
            "records": [],
        }

        text = render_concise_markdown(
            self._payload(),
            material=profile.active_material,
            cell_configuration=profile.cell_description,
            rate=profile.test_current,
            temperature=profile.temperature,
            research_profile=profile,
            literature_result=literature,
        )

        self.assertIn("暂无直接可比基准", text)
        self.assertIn("暂不可判定", text)

    def test_report_preserves_numeric_analysis_when_literature_network_fails(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import render_concise_markdown

        profile = ResearchProfile(
            battery_system="锂硫电池",
            active_material="S/C",
            cell_type="半电池",
            counter_electrode="Li",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="硫质量",
        )
        text = render_concise_markdown(
            self._payload(), None, None, None, None,
            research_profile=profile,
            literature_result={"error": "network unavailable", "records": []},
        )

        self.assertIn("完整循环放电比容量", text)
        self.assertIn("联网检索失败", text)
        self.assertIn("暂不可判定", text)

    def test_scientific_bundle_writes_literature_evidence_and_comparison(self):
        from electrochem_harness.literature import ResearchProfile
        from electrochem_harness.sci_report import create_scientific_bundle

        profile = ResearchProfile(
            battery_system="锂硫电池",
            active_material="S/C",
            cell_type="半电池",
            counter_electrode="Li",
            test_current="0.1 C",
            temperature="25 C",
            normalization_basis="硫质量",
        )
        literature = {
            "source": "Crossref REST API",
            "searched_at": "2026-10-12T00:00:00Z",
            "candidate_count": 1,
            "verified_count": 1,
            "directly_comparable_count": 0,
            "records": [{
                "match_level": "context_only",
                "year": 2024,
                "journal": "Battery Journal",
                "title": "A verified paper",
                "doi": "10.1000/bundle",
                "doi_verified": True,
                "citation_count": 3,
                "metrics": {},
            }],
            "limitations": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "curve.csv"
            output = root / "output"
            source.write_text(
                "测试时间/h,比容量/mAh/g,电压/V\n"
                "0.00,0,1.2\n0.01,100,0.5\n0.01,0,0.6\n"
                "0.02,120,2.5\n0.02,0,2.4\n"
                "0.03,110,0.5\n0.03,0,0.6\n0.04,10,1.0\n",
                encoding="utf-8",
            )
            with patch("electrochem_harness.literature.search_crossref", return_value=literature):
                paths = create_scientific_bundle(
                    source,
                    output,
                    research_profile=profile,
                    search_literature=True,
                    max_literature=1,
                )
            evidence = json.loads(paths["literature"].read_text(encoding="utf-8"))
            report = paths["report"].read_text(encoding="utf-8")
            comparison = paths["comparison"].read_text(encoding="utf-8-sig")

        self.assertEqual(evidence["verified_count"], 1)
        self.assertIn("10.1000/bundle", report)
        self.assertIn("match_level", comparison)


if __name__ == "__main__":
    unittest.main()
