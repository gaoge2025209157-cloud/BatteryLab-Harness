"""Zero-install launcher for LAND CSV/TXT analysis."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.land_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
