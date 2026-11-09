"""Launch the single Harness-v2 desktop workflow."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness_v2.gui import main

if __name__ == "__main__":
    main(ROOT)
