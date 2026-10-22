import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

def _enable_dpi_awareness():
    """Tell Windows the process scales itself.

    Without this, Tk reports a DPI-scaled screen size (for example 1536x960 on a
    1080x683 display), so any window sized from ``winfo_screenwidth`` is drawn
    larger than the physical screen and its footer buttons fall off the bottom.
    """

    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # pragma: no cover - older Windows
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


from electrochem_harness.gui import main, smoke_test


def cli(argv=None):
    parser = argparse.ArgumentParser(description="ElectrochemHarness desktop interface")
    parser.add_argument("--check", action="store_true", help="Create and close the interface to verify Tkinter")
    args = parser.parse_args(argv)
    if args.check:
        _enable_dpi_awareness()
        smoke_test(ROOT)
        print("GUI check passed")
        return 0
    _enable_dpi_awareness()
    main(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
