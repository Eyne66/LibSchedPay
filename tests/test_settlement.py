import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from book_workbench.settlement import (  # noqa: E402
    SettlementValidationError,
    calculate_settlement,
    validate_transfers,
)
from book_workbench.schedule import ScheduleValidationError, generate_schedule, validate_schedule  # noqa: E402


class SettlementTests(unittest.TestCase):
    def test_issued_hours_are_editable_and_zero_difference_is_valid(self):
        result = calculate_settlement(
            [
                {"name": "甲", "actual_hours": 28, "issued_hours": 28},
                {"name": "乙", "actual_hours": 40, "issued_hours": 33},
                {"name": "丙", "actual_hours": 20, "issued_hours": 25},
            ]
        )
        people = {row["name"]: row for row in result["people"]}
        self.assertEqual(people["甲"]["difference_hours"], "0")
        self.assertEqual(people["乙"]["difference_hours"], "7")
        self.assertEqual(people["丙"]["difference_hours"], "-5")
        self.assertEqual(result["totals"]["external_adjustment_hours"], "2")
        self.assertEqual(result["totals"]["draft_transfer_hours"], "5")

    def test_official_hours_cap_is_enforced(self):
        with self.assertRaisesRegex(SettlementValidationError, "above the cap 33"):
            calculate_settlement([{"name": "甲", "actual_hours": 34, "issued_hours": 34}])

    def test_official_hours_cap_can_be_changed_for_this_settlement(self):
        result = calculate_settlement(
            [{"name": "甲", "actual_hours": 40, "issued_hours": 40}],
            issued_cap=40,
        )
        self.assertEqual(result["people"][0]["difference_hours"], "0")

    def test_missing_issued_hours_is_not_guessed(self):
        with self.assertRaisesRegex(SettlementValidationError, "issued_hours is required"):
            calculate_settlement([{"name": "甲", "actual_hours": 28}])

    def test_duplicate_names_are_rejected(self):
        with self.assertRaisesRegex(SettlementValidationError, "duplicate person name"):
            calculate_settlement(
                [
                    {"name": "甲", "actual_hours": 10, "issued_hours": 10},
                    {"name": " 甲 ", "actual_hours": 11, "issued_hours": 11},
                ]
            )

    def test_half_hours_use_exact_decimal_arithmetic(self):
        result = calculate_settlement(
            [
                {"name": "甲", "actual_hours": "10.5", "issued_hours": "10"},
                {"name": "乙", "actual_hours": "9.5", "issued_hours": "10"},
            ]
        )
        self.assertEqual(result["totals"]["difference_hours"], "0")
        self.assertEqual(result["transfers"], [{"payer": "乙", "receiver": "甲", "hours": "0.5"}])

    def test_equal_differences_are_matched_before_splitting(self):
        result = calculate_settlement(
            [
                {"name": "收款甲", "actual_hours": 14, "issued_hours": 10},
                {"name": "收款乙", "actual_hours": 12, "issued_hours": 10},
                {"name": "付款甲", "actual_hours": 6, "issued_hours": 10},
                {"name": "付款乙", "actual_hours": 8, "issued_hours": 10},
            ]
        )
        self.assertEqual(
            result["transfers"],
            [
                {"payer": "付款甲", "receiver": "收款甲", "hours": "4"},
                {"payer": "付款乙", "receiver": "收款乙", "hours": "2"},
            ],
        )

    def test_edited_transfer_plan_is_checked_against_differences(self):
        rows = [
            {"name": "甲", "actual_hours": 40, "issued_hours": 33},
            {"name": "乙", "actual_hours": 26, "issued_hours": 33},
        ]
        self.assertTrue(
            validate_transfers(
                rows,
                [{"payer": "乙", "receiver": "甲", "hours": 7}],
            )["ok"]
        )
        invalid = validate_transfers(
            rows,
            [{"payer": "乙", "receiver": "甲", "hours": 8}],
        )
        self.assertFalse(invalid["ok"])
        self.assertIn("payer 乙 is over-allocated", invalid["errors"])

    def test_transfer_plan_must_fully_reconcile_a_balanced_case(self):
        rows = [
            {"name": "甲", "actual_hours": 40, "issued_hours": 33},
            {"name": "乙", "actual_hours": 26, "issued_hours": 33},
        ]
        incomplete = validate_transfers(rows, [])
        self.assertFalse(incomplete["ok"])
        self.assertIn("payer 乙 is not fully allocated", incomplete["errors"])

    def test_settlement_accepts_random_rosters_of_thirty_to_forty_people(self):
        for count in (30, 40):
            rows = [
                {"name": f"同学{i:02d}", "actual_hours": i, "issued_hours": min(i, 33)}
                for i in range(1, count + 1)
            ]
            result = calculate_settlement(rows)
            self.assertEqual(len(result["people"]), count)
            self.assertEqual(result["checks"]["people_unique"], True)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-24"},
            "days": [{"date": "2026-08-24"}],
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 2},
                {"id": "evening", "name": "晚班", "duration_hours": 3, "required_people": 2},
            ],
            "people": [
                {"name": "甲", "unavailable": []},
                {"name": "乙", "unavailable": []},
            ],
            "assignments": [
                {"date": "2026-08-24", "shift_id": "morning", "people": ["甲", "乙"]},
                {"date": "2026-08-24", "shift_id": "evening", "people": ["甲", "乙"]},
            ],
        }

    def test_same_person_can_work_different_shifts_but_hours_are_summed(self):
        result = validate_schedule(self.payload)
        self.assertTrue(result["ok"])
        self.assertEqual(result["totals"], {
            "planned_slots": 4,
            "filled_slots": 4,
            "vacancy_slots": 0,
            "planned_hours": "10",
            "filled_hours": "10",
        })
        summary = {row["name"]: row for row in result["people"]}
        self.assertEqual(summary["甲"]["assigned_hours"], "5")

    def test_duplicate_unknown_and_unavailable_are_reported(self):
        self.payload["people"][0]["unavailable"] = [
            {"date": "2026-08-24", "shift_id": "morning"}
        ]
        self.payload["assignments"][0]["people"] = ["甲", "甲"]
        result = validate_schedule(self.payload)
        self.assertFalse(result["ok"])
        self.assertTrue(any("duplicate person" in error for error in result["errors"]))
        self.assertTrue(any("unavailable person" in error for error in result["errors"]))

    def test_understaffing_is_a_warning_and_is_counted(self):
        self.payload["assignments"][1]["people"] = ["甲"]
        result = validate_schedule(self.payload)
        self.assertTrue(result["ok"])
        self.assertIn("2026-08-24/evening has 1 vacancy", result["warnings"])
        self.assertEqual(result["totals"]["vacancy_slots"], 1)

    def test_generator_avoids_unavailable_and_returns_editable_assignments(self):
        payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-24"},
            "days": [{"date": "2026-08-24"}],
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 1},
                {"id": "evening", "name": "晚班", "duration_hours": 3, "required_people": 1},
            ],
            "people": [
                {
                    "name": "甲",
                    "unavailable": [{"date": "2026-08-24", "shift_id": "morning"}],
                    "target_hours": 3,
                },
                {"name": "乙", "unavailable": [], "target_hours": 3},
            ],
        }
        result = generate_schedule(payload)
        self.assertTrue(result["validation"]["ok"])
        assignments = result["schedule"]["assignments"]
        self.assertEqual(assignments[0]["people"], ["乙"])
        self.assertEqual(result["validation"]["totals"]["filled_hours"], "5")

    def test_schedule_accepts_a_forty_person_roster(self):
        payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-30"},
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 2},
                {"id": "afternoon", "name": "下午班", "duration_hours": 2, "required_people": 2},
                {"id": "evening", "name": "晚班", "duration_hours": 3, "required_people": 3},
            ],
            "people": [{"name": f"同学{i:02d}", "unavailable": []} for i in range(1, 41)],
        }
        result = generate_schedule(payload)
        self.assertEqual(len(result["validation"]["people"]), 40)
        self.assertEqual(result["validation"]["totals"]["planned_slots"], 49)

    def test_generator_can_balance_each_shift_duration_separately(self):
        payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-26"},
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 2},
                {"id": "evening", "name": "晚班", "duration_hours": 3, "required_people": 2},
            ],
            "people": [{"name": name, "unavailable": []} for name in ["甲", "乙", "丙", "丁"]],
            "allocation_mode": "by_duration",
        }
        result = generate_schedule(payload)
        self.assertTrue(result["validation"]["ok"])
        self.assertEqual(result["schedule"]["allocation_mode"], "by_duration")
        for shift_id in ("morning", "evening"):
            counts = {name: 0 for name in ["甲", "乙", "丙", "丁"]}
            for assignment in result["schedule"]["assignments"]:
                if assignment["shift_id"] == shift_id:
                    for name in assignment["people"]:
                        counts[name] += 1
            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_daily_staffing_override_is_used_for_reference_schedule(self):
        payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-30"},
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 2},
                {"id": "afternoon", "name": "下午班", "duration_hours": 2, "required_people": 2},
                {"id": "evening", "name": "晚班", "duration_hours": 3, "required_people": 3},
            ],
            "people": [{"name": f"同学{i:02d}", "unavailable": []} for i in range(1, 14)],
            "day_requirements": {"2026-08-30": {"evening": 2}},
            "allocation_mode": "by_duration",
        }
        result = generate_schedule(payload)
        self.assertTrue(result["validation"]["ok"])
        self.assertEqual(result["validation"]["totals"]["planned_slots"], 48)
        self.assertEqual(result["validation"]["totals"]["planned_hours"], "116")
        sunday_evening = next(
            row for row in result["validation"]["shift_results"]
            if row["date"] == "2026-08-30" and row["shift_id"] == "evening"
        )
        self.assertEqual(sunday_evening["required_people"], 2)

    def test_missing_individual_targets_keep_the_default_fair_share(self):
        payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-24"},
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 2},
            ],
            "people": [
                {"name": "尽量少排", "unavailable": [], "target_hours": 0},
                {"name": "正常甲", "unavailable": []},
                {"name": "正常乙", "unavailable": []},
            ],
        }
        result = generate_schedule(payload)
        assigned = result["schedule"]["assignments"][0]["people"]
        self.assertEqual(set(assigned), {"正常甲", "正常乙"})

    def test_invalid_unavailable_slot_is_rejected_instead_of_ignored(self):
        payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-24"},
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 1},
            ],
            "people": [
                {
                    "name": "甲",
                    "unavailable": [{"date": "2026-08-24", "shift_id": "typo-shift"}],
                },
            ],
        }
        with self.assertRaisesRegex(ScheduleValidationError, "unknown unavailable shift"):
            generate_schedule(payload)


if __name__ == "__main__":
    unittest.main()
