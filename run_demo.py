import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness import ExperimentContext, KnowledgeBase, run_harness


def main():
    context = ExperimentContext(
        experiment_type="galvanostatic_cycling",
        system_type="demonstration_half_cell",
        electrolyte="待填",
        anode="Li",
        atmosphere="Ar",
        active_mass_mg=10.0,
    )
    knowledge_base = KnowledgeBase(
        ROOT / "knowledge" / "base_rules.json",
        ROOT / "knowledge" / "experiences.jsonl",
    )
    report = run_harness(ROOT / "examples" / "sample_cycling.csv", context, knowledge_base)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
