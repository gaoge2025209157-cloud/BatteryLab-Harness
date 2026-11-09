from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrochem_harness_v2.models import KnowledgeClaim
from electrochem_harness_v2.storage import ResearchStore


class ResearchStoreReviewTests(unittest.TestCase):
    def test_candidate_requires_review_before_becoming_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("P2O5 test", "P2O5|LiTaCl6|Li-In", ["P2O5"])
            claim = KnowledgeClaim.new(
                project_id=project_id,
                source_id="source-1",
                claim_type="performance",
                text="A reported capacity",
                metric_id="discharge_specific_capacity_mAh_g",
                value=152.2,
                unit="mAh/g",
                conditions={"temperature_C": 60},
                evidence_span_ids=["span-1"],
            )
            store.save_claim(claim)
            self.assertEqual(store.list_approved_claims(project_id), [])

            reviewed = store.review_claim(claim.claim_id, "approved", "researcher", "Verified against PDF")
            self.assertEqual(reviewed.status, "approved")
            self.assertEqual([item.claim_id for item in store.list_approved_claims(project_id)], [claim.claim_id])
            self.assertEqual(len(store.list_review_events(claim.claim_id)), 1)

    def test_review_history_is_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("P2O5 test", "P2O5|LiTaCl6|Li-In", ["P2O5"])
            claim = KnowledgeClaim.new(project_id, "source-1", "background", "A background fact")
            store.save_claim(claim)
            store.review_claim(claim.claim_id, "approved", "researcher", "first review")
            store.review_claim(claim.claim_id, "rejected", "researcher", "later rejected")
            self.assertEqual(len(store.list_review_events(claim.claim_id)), 2)
            self.assertEqual(store.get_claim(claim.claim_id).status, "rejected")

    def test_updates_project_name_type_and_keywords_without_losing_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            project_id = store.create_project("初始课题", "卤化物电解质", ["LPSC"])
            updated = store.update_project(project_id, "P₂O₅-LPSC 固态电池", "P₂O₅｜LPSC｜Li-In", ["P₂O₅", "LPSC", "固态电池"])
        self.assertEqual(updated["name"], "P₂O₅-LPSC 固态电池")
        self.assertEqual(updated["material_system"], "P₂O₅｜LPSC｜Li-In")
        self.assertEqual(updated["keywords"], ["P₂O₅", "LPSC", "固态电池"])
