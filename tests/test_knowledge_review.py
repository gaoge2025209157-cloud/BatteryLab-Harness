from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.codex_client import curated_payload_to_claims
from electrochem_harness_v2.models import KnowledgeClaim
from electrochem_harness_v2.storage import ResearchStore


class CuratedKnowledgeTests(unittest.TestCase):
    def test_only_small_codex_selected_set_becomes_reviewable_claims(self):
        candidates = [KnowledgeClaim.new("project-1", "source-1", "performance", "Raw claim", evidence_span_ids=["span-1"])]
        payload = {
            "knowledge_items": [{
                "title": "Key test",
                "claim": "The key test links interface evidence to cycling.",
                "priority": "high",
                "why_selected": "Directly answers the project question.",
                "candidate_claim_ids": [candidates[0].claim_id],
                "source_urls": [],
                "tests": ["XPS", "cycling"],
                "question": "What changes at the interface?",
                "finding": "The interface signal changes after cycling.",
                "how_to_borrow": "Take matched pre/post-cycling XPS samples.",
            }],
            "rejected_items": [],
            "research_gaps": [],
        }
        claims, rejected = curated_payload_to_claims("project-1", candidates, payload)
        self.assertEqual(rejected, [])
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].conditions["review_stage"], "codex_curated")
        self.assertEqual(claims[0].conditions["priority"], "high")

    def test_more_than_six_items_are_rejected(self):
        payload = {"knowledge_items": [{"title": str(i), "claim": "claim", "priority": "high", "why_selected": "reason", "tests": ["XPS"], "question": "q", "finding": "f", "how_to_borrow": "h"} for i in range(7)]}
        claims, rejected = curated_payload_to_claims("project-1", [], payload)
        self.assertEqual(claims, [])
        self.assertIn("at most 6", rejected[0])


class ReviewQueueTests(unittest.TestCase):
    def test_store_lists_only_codex_curated_review_items(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("Test", "P2O5", [])
            raw = KnowledgeClaim.new(project_id, "source-1", "background", "Raw candidate")
            curated = KnowledgeClaim.new(project_id, "source-1", "codex_curated_literature", "精选候选", conditions={"review_stage": "codex_curated", "priority": "high"})
            store.save_claim(raw)
            store.save_claim(curated)
            self.assertEqual([item.text for item in store.list_review_queue(project_id)], ["精选候选"])
            store.review_curated_claims(project_id, "approved", "researcher", "Approved the Codex digest")
            self.assertEqual([item.text for item in store.list_approved_claims(project_id)], ["精选候选"])


if __name__ == "__main__":
    unittest.main()
