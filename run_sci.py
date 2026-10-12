import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.literature import ResearchProfile, collect_research_profile
from electrochem_harness.sci_report import create_scientific_bundle


def _profile_from_args(args):
    return ResearchProfile(
        battery_system=args.battery_system or "",
        active_material=args.active_material or args.material or "",
        cell_type=args.cell_type or args.cell_configuration or "",
        counter_electrode=args.counter_electrode or "",
        test_current=args.test_current or args.rate or "",
        temperature=args.temperature or "",
        normalization_basis=args.normalization_basis or "",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate concise electrochemical report, verified literature comparison, and Origin inputs"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--guided", action="store_true", help="Interactively ask for all comparison metadata")
    parser.add_argument("--search-literature", action="store_true", help="Search Crossref and recheck every retained DOI")
    parser.add_argument("--max-literature", type=int, default=50, help="Maximum candidate DOIs to verify (default: 50)")
    parser.add_argument("--battery-system")
    parser.add_argument("--active-material")
    parser.add_argument("--cell-type")
    parser.add_argument("--counter-electrode")
    parser.add_argument("--test-current")
    parser.add_argument("--normalization-basis")
    parser.add_argument("--temperature")
    # Backward-compatible names from the first concise-report entry point.
    parser.add_argument("--material")
    parser.add_argument("--cell-configuration")
    parser.add_argument("--rate")
    args = parser.parse_args(argv)

    profile = _profile_from_args(args)
    if args.guided:
        profile = collect_research_profile(defaults=profile)
    paths = create_scientific_bundle(
        args.input,
        args.output_dir,
        material=profile.active_material,
        cell_configuration=profile.cell_description,
        rate=profile.test_current,
        temperature=profile.temperature,
        research_profile=profile,
        search_literature=args.search_literature or args.guided,
        max_literature=max(1, min(args.max_literature, 200)),
    )
    for name, path in paths.items():
        print("{}={}".format(name, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
