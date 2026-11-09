"""Retry only the formal Origin stage for an existing run after a recoverable plotting failure."""
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
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data", required=True, type=Path)
    args = parser.parse_args()
    workflow = ResearchWorkflow(ROOT / "knowledge" / "research.sqlite3", ROOT / "outputs" / "research_cockpit")
    result = workflow.prepare_origin(args.project_id, args.run_id, args.data)
    print("{}: {}".format(result.status, result.reason or result.project_path))
