from __future__ import annotations

import unittest

from electrochem_harness_v2.web_research import validate_web_research


class WebResearchTests(unittest.TestCase):
    def test_requires_https_sources_and_marks_all_results_candidate(self):
        payload = {
            "sources": [{"title": "Review", "url": "https://example.org/review", "source_type": "journal", "claims": [{"metric": "specific_capacity", "value": 180, "unit": "mAh/g", "conditions": {}, "evidence": "authors report 180", "limitations": []}]}],
            "mainstream_systems": [{"system": "NMC", "specific_capacity_mAh_g": 180, "average_discharge_voltage_V": 3.7, "theoretical_specific_energy_Wh_kg": 666, "source_urls": ["https://example.org/review"], "limitations": []}],
            "commercial_batteries": [{"chemistry": "LFP", "energy_density_Wh_kg": 160, "basis": "cell", "source_urls": ["https://example.org/review"]}],
            "standards": [],
            "theoretical_model": {"formula": "P2O5", "electron_transfer": 10, "average_voltage_V": 1.5, "source_urls": ["https://example.org/review"], "limitations": ["candidate"]},
        }
        result = validate_web_research(payload)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["sources"][0]["evidence_level"], "web_search_candidate")
        self.assertEqual(result["commercial_batteries"][0]["chemistry"], "LFP")

    def test_accepts_representative_capacity_alias(self):
        payload = {
            "sources": [{"title": "Primary paper", "url": "https://example.org/paper"}],
            "priority_sources": [], "knowledge_digest": [], "standards": [], "theoretical_model": None,
            "mainstream_systems": [{"system": "LPSC–carbon", "representative_specific_capacity_mAh_g": 965, "source_urls": ["https://example.org/paper"]}],
        }
        result = validate_web_research(payload)
        self.assertEqual(result["mainstream_systems"][0]["specific_capacity_mAh_g"], 965)

        with self.assertRaises(ValueError):
            validate_web_research({"sources": [{"title": "bad", "url": "http://example.org"}], "mainstream_systems": [], "standards": [], "theoretical_model": None})


    def test_validates_codex_curated_knowledge_digest_and_priority_sources(self):
        payload = {
            "sources": [{"title": "Primary paper", "url": "https://example.org/paper", "source_type": "journal", "claims": []}],
            "priority_sources": [{"title": "Primary paper", "url": "https://example.org/paper", "why_relevant": "Directly tests interface stability."}],
            "knowledge_digest": [{
                "title": "Interface stability test",
                "claim": "The paper compares cycling before and after interface treatment.",
                "priority": "high",
                "why_selected": "It answers the current project's interface question.",
                "tests": ["cycling", "XPS"],
                "question": "Does the interface change during cycling?",
                "finding": "The treatment changes the post-cycling interface signal.",
                "how_to_borrow": "Add matched pre/post-cycling XPS samples.",
                "source_urls": ["https://example.org/paper"],
            }],
            "mainstream_systems": [],
            "standards": [],
            "theoretical_model": None,
        }
        result = validate_web_research(payload)
        self.assertEqual(result["knowledge_digest"][0]["evidence_status"], "web_search_candidate")
        self.assertEqual(result["priority_sources"][0]["url"], "https://example.org/paper")

    def test_discards_curated_knowledge_with_unlisted_source_but_keeps_research(self):
        payload = {
            "sources": [{"title": "Primary paper", "url": "https://example.org/paper"}],
            "priority_sources": [],
            "knowledge_digest": [{
                "title": "Untraceable", "claim": "x", "priority": "high", "why_selected": "x",
                "tests": ["XPS"], "question": "x", "finding": "x", "how_to_borrow": "x",
                "source_urls": ["https://example.org/not-listed"],
            }],
            "mainstream_systems": [], "standards": [], "theoretical_model": None,
        }
        result = validate_web_research(payload)
        self.assertEqual(result["knowledge_digest"], [])
        self.assertEqual(len(result["rejected_knowledge_digest"]), 1)

    def test_preserves_codex_research_synthesis_for_academic_report(self):
        payload = {
            "sources": [{"title": "Primary paper", "url": "https://example.org/paper"}],
            "priority_sources": [],
            "knowledge_digest": [],
            "mainstream_systems": [],
            "standards": [],
            "theoretical_model": None,
            "research_synthesis": {
                "search_question": "What limits the LPSC composite cathode?",
                "data_literature_connection": ["High polarization motivates interface-focused studies."],
                "evidence_boundaries": ["Web evidence requires review."],
            },
        }
        result = validate_web_research(payload)
        self.assertEqual(result["research_synthesis"]["search_question"], "What limits the LPSC composite cathode?")

    def test_discards_unlisted_theory_but_keeps_valid_research(self):
        payload = {
            "sources": [{"title": "Primary paper", "url": "https://example.org/paper"}],
            "priority_sources": [], "knowledge_digest": [], "mainstream_systems": [], "standards": [],
            "theoretical_model": {"formula": "P2O5", "electron_transfer": 16, "source_urls": ["https://example.org/not-listed"]},
        }
        result = validate_web_research(payload)
        self.assertIsNone(result["theoretical_model"])

    def test_priority_source_without_title_uses_listed_source_title(self):
        payload = {
            "sources": [{"title": "Primary paper", "url": "https://example.org/paper"}],
            "priority_sources": [{"url": "https://example.org/paper", "why_relevant": "Direct evidence."}],
            "knowledge_digest": [],
            "mainstream_systems": [],
            "standards": [],
            "theoretical_model": None,
        }
        result = validate_web_research(payload)
        self.assertEqual(result["priority_sources"][0]["title"], "Primary paper")

    def test_incomplete_priority_source_does_not_discard_valid_research(self):
        payload = {
            "sources": [{"title": "Primary paper", "url": "https://example.org/paper"}],
            "priority_sources": [{"why_relevant": "No URL"}],
            "knowledge_digest": [],
            "mainstream_systems": [],
            "standards": [],
            "theoretical_model": None,
        }
        result = validate_web_research(payload)
        self.assertEqual(result["sources"][0]["title"], "Primary paper")
        self.assertEqual(result["priority_sources"], [])
