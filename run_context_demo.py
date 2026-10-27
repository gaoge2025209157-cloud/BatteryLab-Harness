#!/usr/bin/env python3
"""Build and save one demonstration context without calling an LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from electrochem_harness.context_management import ContextBuilder, ContextStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a BatteryLab Harness context bundle")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "examples" / "context_management" / "context_request.json",
        help="JSON context request",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "demo_output",
        help="Directory used for task state and context output",
    )
    parser.add_argument("--max-input-tokens", type=int, default=8000)
    args = parser.parse_args()

    request = json.loads(args.input.read_text(encoding="utf-8"))
    result = ContextBuilder(max_input_tokens=args.max_input_tokens).build(request)
    task = request["task"]
    store = ContextStore(args.output)
    store.save_state(
        session_id=task["session_id"],
        task_id=task["task_id"],
        task=task,
        experiment_profile=request["experiment_profile"],
        conversation_summary=request.get("conversation_summary", {}),
        permissions=request["permissions"],
    )
    bundle_path, manifest_path = store.save_build(result)

    print("Context built successfully")
    print("context_hash:", result.context_hash)
    print("estimated_input_tokens:", result.estimated_input_tokens)
    print("available_tools:", ", ".join(result.manifest["available_tools"]))
    print("bundle:", bundle_path)
    print("manifest:", manifest_path)
    if result.warnings:
        print("warnings:", ", ".join(result.warnings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
