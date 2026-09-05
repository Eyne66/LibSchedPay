"""Regression cases for the four observed defects and the public runtime."""
import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from book_workbench.browser_api import dispatch, request_json
from book_workbench.schedule import ScheduleValidationError, generate_schedule, validate_schedule
from book_workbench.service import _validated_export_payload
from book_workbench.settlement import SettlementValidationError, calculate_settlement
from book_workbench.table_import import _matrix_to_rows, _read_xlsx_sheets, parse_uploaded_table


def schedule_fixture():
    return {
        "cycle": {"start_date": "2026-09-07", "end_date": "2026-09-07"},
        "days": [{"date": "2026-09-07", "label": "周一 2026-09-07"}],
        "people": [{"name": "小王"}, {"name": "小李"}],
        "shifts": [{"id": "evening", "name": "晚班", "start": "19:00", "end": "22:00", "duration_hours": 3, "required_people": 2}],
        "assignments": [{"date": "2026-09-07", "shift_id": "evening", "people": ["小王", "小李"]}],
    }


class WebRegressions(unittest.TestCase):
    def test_r1_issued_column_before_actual_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hours.csv"
            path.write_text("姓名,下发工时,实际工时\n甲,33,40\n乙,33,26\n", encoding="utf-8")
            rows = parse_uploaded_table(path, "settlement")["rows"]
        result = calculate_settlement(rows, issued_cap=33)
        self.assertEqual(result["totals"]["actual_hours"], "66")
        self.assertEqual(result["transfers"], [{"payer": "乙", "receiver": "甲", "hours": "7"}])

    def test_r1_missing_actual_or_ambiguous_columns_rejected(self):
        cases = [
            "姓名,下发工时\n甲,33\n",
            "姓名,实际工时,工时\n甲,40,26\n",
            "姓名,实际工时,实际工时\n甲,40,26\n",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hours.csv"
            for content in cases:
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    parse_uploaded_table(path, "settlement")
        with self.assertRaises(ValueError):
            _matrix_to_rows([["姓名", "实际工时", "实际工时"], ["甲", 1, 2]], "settlement")

    def test_r2_whitespace_alias_cannot_fill_two_positions(self):
        payload = schedule_fixture()
        payload["assignments"][0]["people"] = ["小王", "小 王"]
        self.assertFalse(validate_schedule(payload)["ok"])
        with self.assertRaises(ScheduleValidationError):
            _validated_export_payload("schedule", {"schedule": payload})

    def test_r2_canonical_name_is_counted_in_excel(self):
        payload = schedule_fixture()
        payload["assignments"][0]["people"] = ["小 王", "小李"]
        result = dispatch("/api/export/schedule", {"schedule": payload})
        sheets = self.read_export(result)
        self.assertIn(["2026-09-07", "晚班", "小王", 3], sheets[1])
        self.assertIn(["2026-09-07", "周一 2026-09-07", "晚班", "19:00", "22:00", 3, 2], sheets[2])
        person = next(row for row in sheets[0] if len(row) > 1 and row[1] == "小王")
        self.assertEqual(person[2:5], [1, 1, 3])

    def test_r4_complete_unknown_rule_rejected_at_python_boundary(self):
        payload = schedule_fixture()
        payload["constraints"] = [{"name": "未录入的人", "date": "2026-09-07", "shift_id": "evening"}]
        for operation in (validate_schedule, generate_schedule):
            with self.subTest(operation=operation), self.assertRaisesRegex(ScheduleValidationError, "名单"):
                operation(payload)

    def test_confirmed_rule_whitespace_resolves_and_is_enforced(self):
        payload = schedule_fixture()
        payload["constraints"] = [{"name": "小 王", "date": "2026-09-07", "shift_id": "evening"}]
        result = generate_schedule(payload)
        self.assertEqual(result["schedule"]["assignments"][0]["people"], ["小李"])
        self.assertEqual(result["validation"]["totals"]["vacancy_slots"], 1)

    def test_actual_summary_exports_without_issued_hours_or_schedule(self):
        result = dispatch("/api/export/settlement-summary", {
            "period_start": "2026-09-01", "period_end": "2026-09-30",
            "people": [{"name": "甲", "actual_hours": "0.1"}, {"name": "乙", "actual_hours": "0.2"}],
        })
        sheet = self.read_export(result)[0]
        total = next(row for row in sheet if row[0] == "合计")
        self.assertEqual(total[2], 0.3)

    def test_unbalanced_draft_then_edited_final_hours_only(self):
        payload = {"period_start": "2026-09-01", "period_end": "2026-09-30", "issued_cap": 35,
                   "people": [{"name": "甲", "actual_hours": 40, "issued_hours": 35}, {"name": "乙", "actual_hours": 20, "issued_hours": 20}], "transfers": [], "draft": True}
        self.assertTrue(dispatch("/api/export/settlement", payload)["ok"])
        payload["draft"] = False
        with self.assertRaises(SettlementValidationError):
            dispatch("/api/export/settlement", payload)
        payload["people"][1]["issued_hours"] = 25
        payload["transfers"] = [{"payer": "乙", "receiver": "甲", "hours": 5}]
        sheet = self.read_export(dispatch("/api/export/settlement-public", payload))[0]
        self.assertEqual(sheet[1], ["甲5", "乙-5"])
        self.assertEqual(payload["people"][1]["actual_hours"], 20)

    def test_zero_difference_needs_no_transfer_and_cap_is_per_run(self):
        for cap in (30, 35, 40):
            payload = {"issued_cap": cap, "people": [{"name": "甲", "actual_hours": 28, "issued_hours": 28}], "transfers": []}
            self.assertTrue(dispatch("/api/export/settlement-public", payload)["ok"])
            payload["people"][0]["issued_hours"] = cap + 1
            with self.assertRaises(SettlementValidationError):
                dispatch("/api/export/settlement", payload)

    def test_json_adapter_returns_validation_errors(self):
        result = json.loads(request_json("/api/settlement/calculate", json.dumps({"people": [], "issued_cap": 35})))
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def read_export(self, result):
        content = base64.b64decode(result["file_base64"])
        self.assertTrue(content.startswith(b"PK"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / result["path"]
            path.write_bytes(content)
            return _read_xlsx_sheets(path)


if __name__ == "__main__":
    unittest.main()
