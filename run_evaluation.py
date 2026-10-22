"""Run the E-01..E-12 system evaluation and write reviewable outputs."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.evaluation import run_suite


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the E-01..E-12 controlled-Harness evaluation suite"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "release" / "evaluation",
        help="Where evaluation.json and evaluation.md are written",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Scratch directory for the twelve controlled runs (default: release/evaluation-work)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Only print the summary line"
    )
    args = parser.parse_args(argv)

    report = run_suite(ROOT, work_dir=args.work_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "evaluation.json"
    markdown_path = output_dir / "evaluation.md"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")

    if not args.quiet:
        for case in report.cases:
            print(
                "  {} {:<10} {}".format(
                    "PASS" if case.passed else "FAIL", case.case_id, case.detail
                )
            )
        print("")
    print(
        "E-01~E-12: {}/{} passed in {:.1f}s".format(
            report.passed, len(report.cases), report.elapsed_seconds
        )
    )
    for key in (
        "blocking_detection_rate",
        "unauthorized_execution_rate",
        "issue_recognition_rate",
        "false_positive_rate",
        "artifact_completeness",
        "repeat_hash_consistency",
    ):
        print("  {:<32} {}".format(key, report.metrics.get(key)))
    print("")
    print("json={}".format(json_path))
    print("markdown={}".format(markdown_path))
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
