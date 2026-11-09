"""Run local PDF, metadata search, data analysis, Origin, and report stages for authorized inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness_v2.workflow import ResearchWorkflow


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--conditions", default="")
    args = parser.parse_args()
    keywords = [item.strip() for item in args.keywords.split(";") if item.strip()]
    conditions = dict(item.split("=", 1) for item in args.conditions.split(";") if "=" in item)
    workflow = ResearchWorkflow(ROOT / "knowledge" / "research.sqlite3", ROOT / "outputs" / "research_cockpit")
    project_id = workflow.create_project(args.name, args.material, keywords)
    search = workflow.search_literature(project_id, keywords)
    document = workflow.learn_local_pdf(project_id, args.pdf)
    run = workflow.analyze_data(project_id, args.data, conditions)
    origin = workflow.prepare_origin(project_id, run.run_id, args.data)
    report = workflow.build_report(project_id, run.run_id)
    print(json.dumps({
        "project_id": project_id,
        "search_status": search.status,
        "pdf_status": document.extraction_status,
        "pdf_sha256": document.sha256,
        "run_id": run.run_id,
        "analysis_status": run.status,
        "origin_status": origin.status,
        "origin_reason": origin.reason,
        "report": str(report),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
