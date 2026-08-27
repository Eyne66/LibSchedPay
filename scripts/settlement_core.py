#!/usr/bin/env python3
"""Run the deterministic work-hour settlement core on JSON or CSV input."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from book_workbench.settlement import SettlementValidationError, calculate_settlement  # noqa: E402


def read_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        rows = payload.get("people")
    else:
        rows = payload
    if not isinstance(rows, list):
        raise SettlementValidationError("input must be a JSON list or an object with a people list")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--issued-cap", default="33", help="maximum official issued hours per person")
    args = parser.parse_args()

    try:
        result = calculate_settlement(read_rows(args.input), issued_cap=args.issued_cap)
    except (OSError, json.JSONDecodeError, csv.Error, SettlementValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "totals": result["totals"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
