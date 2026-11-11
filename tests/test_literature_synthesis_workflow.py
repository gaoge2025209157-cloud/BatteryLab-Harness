from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrochem_harness_v2.codex_client import curated_payload_to_claims
from electrochem_harness_v2.models import KnowledgeClaim
from electrochem_harness_v2.workflow import ResearchWorkflow


class LiteratureSynthesisWorkflowTests(unittest.TestCase):
    def test_workflow_persists_only_codex_digest_as_review_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = ResearchWorkflow(root / "research.sqlite3", root / "outputs")
            project_id = workflow.create_project("Test", "P2O5|LiTaCl6", ["P2O5"])
            raw = KnowledgeClaim.new(project_id, "source-1", "background", "Raw PDF candidate", evidence_span_ids=["span-1"])
            workflow.store.save_claim(raw)
            digest = {
                "knowledge_items": [{
                    "title": "关键界面测试",
                    "claim": "循环前后界面表征可区分界面变化。",
                    "priority": "high",
                    "why_selected": "直接回答当前课题的界面稳定性问题。",
                    "candidate_claim_ids": [raw.claim_id],
                    "source_urls": [],
                    "tests": ["XPS"],
                    "question": "界面是否发生变化？",
                    "finding": "需要用前后状态对照确认。",
                    "how_to_borrow": "增加循环前后 XPS 对照样品。",
                }],
                "rejected_items": [],
                "research_gaps": ["需要确认质量分母"],
            }
            curated, _ = curated_payload_to_claims(project_id, [raw], digest)
            with patch("electrochem_harness_v2.workflow.CodexResearchClient") as client_type:
                client = client_type.return_value
                client.synthesize_literature.return_value = ("thread-1", digest, curated, [])
                result = workflow.curate_literature(project_id, "run-1", online_research={})
            self.assertEqual(result["status"], "REVIEW_REQUIRED")
            self.assertEqual(len(workflow.store.list_review_queue(project_id)), 1)
            saved = json.loads((root / "outputs" / project_id / "runs" / "run-1" / "literature_review.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["research_gaps"], ["需要确认质量分母"])
            client.synthesize_literature.assert_called_once()
            managed_context = client.synthesize_literature.call_args.args[0]
            self.assertEqual(managed_context["schema_version"], "2.0")
            self.assertEqual(managed_context["stage"], "literature_synthesis")
            self.assertEqual(managed_context["candidate_knowledge"][0]["status"], "candidate")


if __name__ == "__main__":
    unittest.main()
