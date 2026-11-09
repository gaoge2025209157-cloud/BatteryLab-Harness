from __future__ import annotations

import unittest

from electrochem_harness_v2.benchmarks import build_benchmark_topics
from electrochem_harness_v2.search import LiteratureSearchAdapter


class BenchmarkSearchTests(unittest.TestCase):
    def test_builds_topics_from_detected_gcd_metrics(self):
        topics = build_benchmark_topics("P2O5 LiTaCl6 solid-state battery", {
            "gcd_summary": {
                "latest_average_discharge_voltage_V": 1.2,
                "latest_polarization_voltage_V": 0.8,
                "latest_capacity_retention_percent": 49.0,
                "latest_coulombic_efficiency_percent": 96.0,
            },
            "other_performance": {"interfacial_resistance_ohm": 120.0},
        })
        joined = " ".join(topics)
        self.assertIn("specific capacity", joined)
        self.assertIn("average discharge voltage", joined)
        self.assertIn("theoretical specific energy", joined)
        self.assertIn("capacity retention", joined)
        self.assertIn("interfacial resistance ohm", joined)
        self.assertNotIn("industry standard", joined)

    def test_openalex_abstract_is_marked_abstract_only(self):
        crossref = lambda _url: {"message": {"items": []}}
        openalex = lambda _url: {"results": [{
            "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1000/demo", "display_name": "Demo",
            "publication_year": 2025, "authorships": [], "abstract_inverted_index": {"solid": [0], "battery": [1]},
            "primary_location": {"landing_page_url": "https://example.org/demo"},
        }]}
        result = LiteratureSearchAdapter(transport=crossref, openalex_transport=openalex).search(["solid battery"])
        self.assertEqual(result.records[0]["source_level"], "abstract_only")
        self.assertEqual(result.records[0]["abstract"], "solid battery")
        self.assertEqual(result.records[0]["doi"], "10.1000/demo")


if __name__ == "__main__":
    unittest.main()
