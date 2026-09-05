"""Whole-cycle fairness regressions, checked against independent feasible plans."""
import base64
import copy
import itertools
import json
import sys
import tempfile
import unittest
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from book_workbench.browser_api import dispatch
from book_workbench.schedule import generate_schedule, validate_schedule
from book_workbench.schedule_balance import balance_schedule
from book_workbench.table_import import _read_xlsx_sheets


def weekly_fixture():
    return json.loads((ROOT / "tests/fixtures/schedule_fairness.json").read_text(encoding="utf-8"))


def exhaustive_minimum_spread(payload):
    """Enumerate actual assignments, independently of the quota/flow solver."""
    alternatives = []
    durations = []
    for day in payload["days"]:
        for shift in payload["shifts"]:
            eligible = [p["name"] for p in payload["people"] if
                        {"date": day["date"], "shift_id": shift["id"]} not in p.get("unavailable", [])]
            required = payload.get("day_requirements", {}).get(day["date"], {}).get(shift["id"], shift["required_people"])
            alternatives.append(list(itertools.combinations(eligible, min(required, len(eligible)))))
            durations.append(Decimal(str(shift["duration_hours"])))
    best = None
    for assignments in itertools.product(*alternatives):
        hours = {p["name"]: Decimal(0) for p in payload["people"]}
        for selected, duration in zip(assignments, durations):
            for name in selected:
                hours[name] += duration
        spread = max(hours.values()) - min(hours.values())
        best = spread if best is None else min(best, spread)
    return best


class ScheduleBalanceTests(unittest.TestCase):
    def test_35_people_with_unavailability_can_all_receive_seven_hours(self):
        fixture = weekly_fixture()
        witness = validate_schedule({**fixture["input"], "assignments": fixture["witness"]})
        self.assertTrue(witness["ok"])
        self.assertEqual({p["assigned_hours"] for p in witness["people"]}, {"7"})
        for mode in ("total_hours", "by_duration"):
            with self.subTest(mode=mode):
                payload = {**fixture["input"], "allocation_mode": mode}
                original = copy.deepcopy(payload)
                result = generate_schedule(payload)
                self.assertEqual(payload, original)
                self.assertTrue(result["validation"]["ok"])
                self.assertEqual(result["validation"]["totals"]["filled_hours"], "245")
                self.assertEqual(result["validation"]["totals"]["vacancy_slots"], 0)
                self.assertEqual(Counter(p["assigned_hours"] for p in result["validation"]["people"]), {"7": 35})
                self.assertEqual(result["validation"]["fairness"]["hour_spread"], "0")
                self.assertTrue(result["balance_report"]["minimum_spread_proven"])
                self.assertEqual(generate_schedule(payload), result)

    def test_unrestricted_total_hours_is_equal_too(self):
        payload = weekly_fixture()["input"]
        payload["allocation_mode"] = "total_hours"
        for person in payload["people"]:
            person["unavailable"] = []
        result = generate_schedule(payload)
        self.assertEqual(Counter(p["assigned_hours"] for p in result["validation"]["people"]), {"7": 35})

    def test_two_hour_morning_and_afternoon_share_one_count_group(self):
        payload = weekly_fixture()["input"]
        payload["allocation_mode"] = "by_duration"
        result = generate_schedule(payload)
        counts = {p["name"]: Counter() for p in payload["people"]}
        lengths = {s["id"]: Decimal(str(s["duration_hours"])) for s in payload["shifts"]}
        for assignment in result["schedule"]["assignments"]:
            for name in assignment["people"]:
                counts[name][lengths[assignment["shift_id"]]] += 1
        self.assertTrue(result["balance_report"]["duration_counts_floor_ceil"])
        self.assertTrue(all(c == {Decimal(2): 2, Decimal(3): 1} for c in counts.values()))

    def test_reported_optimum_matches_exhaustive_assignments(self):
        for restricted in (False, True):
            for fractional in (False, True):
                for mode in ("total_hours", "by_duration"):
                    with self.subTest(restricted=restricted, fractional=fractional, mode=mode):
                        payload = {
                            "cycle": {"start_date": "2026-09-07", "end_date": "2026-09-08"},
                            "days": [{"date": "2026-09-07"}, {"date": "2026-09-08"}],
                            "shifts": [{"id": "am", "duration_hours": "1.5" if fractional else 2, "required_people": 1},
                                       {"id": "pm", "duration_hours": "2.5" if fractional else 3, "required_people": 1}],
                            "people": [{"name": name, "unavailable": []} for name in ("甲", "乙", "丙")],
                            "day_requirements": {"2026-09-08": {"am": 2}},
                            "allocation_mode": mode,
                        }
                        if restricted:
                            payload["people"][0]["unavailable"] = [{"date": d["date"], "shift_id": "pm"} for d in payload["days"]]
                            payload["people"][1]["unavailable"] = [{"date": "2026-09-07", "shift_id": "am"}]
                        result = generate_schedule(payload)
                        self.assertTrue(result["validation"]["ok"])
                        self.assertTrue(result["balance_report"]["minimum_spread_proven"])
                        self.assertEqual(Decimal(result["validation"]["fairness"]["hour_spread"]), exhaustive_minimum_spread(payload))

    def test_unavailability_can_make_equal_hours_impossible(self):
        payload = weekly_fixture()["input"]
        person = payload["people"][-1]
        days = sorted({a["date"] for a in weekly_fixture()["witness"]})
        person["unavailable"] = [{"date": day, "shift_id": shift["id"]}
                                 for day in days for shift in payload["shifts"]
                                 if shift["duration_hours"] == 2]
        result = generate_schedule(payload)
        self.assertTrue(result["validation"]["ok"])
        self.assertEqual(result["validation"]["totals"]["vacancy_slots"], 0)
        self.assertGreater(Decimal(result["validation"]["fairness"]["hour_spread"]), 0)
        self.assertNotEqual(next(p for p in result["validation"]["people"] if p["name"] == person["name"])["assigned_hours"], "7")

    def test_search_limit_preserves_valid_draft_without_false_impossibility(self):
        fixture = weekly_fixture()
        assignments, report = balance_schedule(fixture["input"], fixture["witness"], node_budget=0)
        self.assertEqual(assignments, fixture["witness"])
        self.assertEqual(report["status"], "search_limit")
        self.assertFalse(report["minimum_spread_proven"])
        self.assertTrue(validate_schedule({**fixture["input"], "assignments": assignments})["ok"])

    def test_export_contains_the_same_balanced_personal_hours(self):
        result = generate_schedule(weekly_fixture()["input"])
        export = dispatch("/api/export/schedule", {"schedule": result["schedule"]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.xlsx"
            path.write_bytes(base64.b64decode(export["file_base64"]))
            sheet = _read_xlsx_sheets(path)[0]
        names = {p["name"] for p in result["validation"]["people"]}
        hours_column = next(r for r in sheet if "总时长(h)" in r).index("总时长(h)")
        rows = [r for r in sheet if len(r) > 4 and r[1] in names]
        self.assertEqual(len(rows), 35)
        self.assertTrue(all(r[hours_column] == 7 for r in rows))
