import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.ground_truth import run_ground_truth_suite


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run Phase 2 scientific ground-truth validation")
    parser.add_argument(
        "suite",
        nargs="?",
        type=Path,
        default=ROOT / "standards" / "ground_truth_v1.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_ground_truth_suite(args.suite)
    payload = result.to_dict()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.numeric_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
