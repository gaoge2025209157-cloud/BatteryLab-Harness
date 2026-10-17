import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.replicates import run_replicate_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze a same-condition replicate-cell group")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result, paths = run_replicate_manifest(args.manifest, args.output_dir)
    print("interpretation={}".format(result.interpretation))
    for name, path in paths.items():
        print("{}={}".format(name, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
