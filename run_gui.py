import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.gui import main, smoke_test


def cli(argv=None):
    parser = argparse.ArgumentParser(description="ElectrochemHarness desktop interface")
    parser.add_argument("--check", action="store_true", help="Create and close the interface to verify Tkinter")
    args = parser.parse_args(argv)
    if args.check:
        smoke_test(ROOT)
        print("GUI check passed")
        return 0
    main(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
