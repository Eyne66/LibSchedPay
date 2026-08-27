#!/usr/bin/env python3
"""Validate a confirmed schedule draft from JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from book_workbench.schedule import ScheduleValidationError, generate_schedule, validate_schedule  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--generate", action="store_true", help="generate a draft before validating it")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = generate_schedule(payload) if args.generate else {"validation": validate_schedule(payload), "schedule": payload}
    except (OSError, json.JSONDecodeError, ScheduleValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation = result["validation"]
    print(json.dumps({"ok": validation["ok"], "output": str(args.output), "totals": validation["totals"]}, ensure_ascii=False))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
