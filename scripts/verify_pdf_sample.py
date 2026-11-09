"""Inspect a locally authorized PDF and print its coverage summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from electrochem_harness_v2.pdf_reader import LocalPdfReader


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    result = LocalPdfReader().read(args.pdf)
    print(json.dumps({
        "sha256": result.document.sha256,
        "page_count": result.document.page_count,
        "extraction_status": result.document.extraction_status,
        "coverage_manifest": result.document.coverage_manifest,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
