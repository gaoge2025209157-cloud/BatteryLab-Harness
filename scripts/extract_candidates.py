"""Send only bounded, page-addressable local evidence to Codex for candidate extraction."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness_v2.workflow import ResearchWorkflow


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--thread-id")
    args = parser.parse_args()
    workflow = ResearchWorkflow(ROOT / "knowledge" / "research.sqlite3", ROOT / "outputs" / "research_cockpit")
    thread_id, claims, rejected = workflow.extract_pdf_candidates(args.project_id, args.source_id, args.thread_id)
    print("thread_id={}".format(thread_id))
    print("candidate_claims={}".format(len(claims)))
    print("rejected_claims={}".format(len(rejected)))
