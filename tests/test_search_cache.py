from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.storage import ResearchStore


class SearchCacheTests(unittest.TestCase):
    def test_search_knowledge_is_reusable_across_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            store.save_search_cache("p2o5|capacity", {"records": [{"title": "Paper"}]})
            self.assertEqual(store.get_search_cache("p2o5|capacity")["records"][0]["title"], "Paper")
            store.migrate()
            self.assertEqual(store.get_search_cache("p2o5|capacity")["records"][0]["title"], "Paper")


if __name__ == "__main__":
    unittest.main()


class CodexResearchCacheCompatibilityTests(unittest.TestCase):
    def test_old_cached_web_research_without_priority_digest_is_not_reused(self):
        from electrochem_harness_v2.workflow import ResearchWorkflow

        self.assertFalse(ResearchWorkflow._is_current_web_research_cache({
            "codex_web_research": {"sources": [], "mainstream_systems": [], "standards": []},
        }))
        self.assertTrue(ResearchWorkflow._is_current_web_research_cache({
            "codex_web_research": {"sources": [], "priority_sources": [], "knowledge_digest": [], "research_synthesis": {}, "commercial_batteries": [], "mainstream_systems": [], "standards": []},
        }))
