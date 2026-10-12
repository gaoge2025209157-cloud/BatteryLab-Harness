"""Command-line entry point for LAND CSV/TXT exports."""

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .guidance import run_harness_points
from .knowledge import KnowledgeBase
from .land import LandImportConfig, load_land_export
from .land_curve import analyze_land_capacity_curve
from .models import ExperimentContext


def _parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Read a LAND CSV/TXT export and generate an auditable JSON report."
    )
    parser.add_argument("input", type=Path, help="LAND CSV/TXT export")
    parser.add_argument("--output", type=Path, required=True, help="output JSON path")
    parser.add_argument("--active-mass-mg", type=float)
    parser.add_argument("--system-type")
    parser.add_argument("--electrolyte")
    parser.add_argument("--anode")
    parser.add_argument("--atmosphere")
    parser.add_argument("--charge-current-sign", choices=("positive", "negative"), default="positive")
    parser.add_argument("--current-unit", choices=("auto", "A", "mA", "uA"), default="auto")
    parser.add_argument("--voltage-unit", choices=("auto", "V", "mV"), default="auto")
    parser.add_argument("--time-unit", choices=("auto", "s", "min", "h"), default="auto")
    parser.add_argument("--cycle-column")
    parser.add_argument("--time-column")
    parser.add_argument("--current-column")
    parser.add_argument("--voltage-column")
    parser.add_argument("--rules", type=Path, default=project_root / "knowledge" / "base_rules.json")
    parser.add_argument("--experiences", type=Path, default=project_root / "knowledge" / "experiences.jsonl")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    column_map = {
        name: value
        for name, value in {
            "cycle": args.cycle_column,
            "time": args.time_column,
            "current": args.current_column,
            "voltage": args.voltage_column,
        }.items()
        if value
    }
    context = ExperimentContext(
        experiment_type="galvanostatic_cycling",
        system_type=args.system_type,
        electrolyte=args.electrolyte,
        anode=args.anode,
        atmosphere=args.atmosphere,
        active_mass_mg=args.active_mass_mg,
    )
    try:
        imported = load_land_export(
            args.input,
            LandImportConfig(
                charge_current_sign=args.charge_current_sign,
                current_unit=args.current_unit,
                voltage_unit=args.voltage_unit,
                time_unit=args.time_unit,
                column_map=column_map,
            ),
        )
    except ValueError as raw_mode_error:
        try:
            payload = analyze_land_capacity_curve(args.input)
        except ValueError:
            raise raw_mode_error
        payload["experiment_context"] = context.to_dict()
    else:
        report = run_harness_points(
            imported.points,
            context,
            KnowledgeBase(args.rules, args.experiences),
        )
        payload = {
            "import_metadata": imported.metadata(),
            "experiment_context": context.to_dict(),
            "report": report.to_dict(),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("LAND report written to {}".format(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
