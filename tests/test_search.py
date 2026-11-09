from __future__ import annotations

import unittest

from electrochem_harness_v2.search import LiteratureSearchAdapter


class LiteratureSearchAdapterTests(unittest.TestCase):
    def test_records_query_and_marks_results_metadata_only(self):
        def transport(_url: str) -> dict:
            return {"message": {"items": [{"DOI": "10.1000/example", "title": ["Example paper"], "author": [{"family": "Li"}]}]}}

        result = LiteratureSearchAdapter(transport=transport).search(["P2O5", "halide electrolyte"])

        self.assertEqual(result.query, "P2O5 halide electrolyte")
        self.assertEqual(result.records[0]["doi"], "10.1000/example")
        self.assertEqual(result.records[0]["source_level"], "metadata_only")
        self.assertTrue(result.searched_at)


if __name__ == "__main__":
    unittest.main()
