import base64
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from book_workbench.schedule import generate_schedule  # noqa: E402
from book_workbench.settlement import SettlementValidationError  # noqa: E402
from workbench import server as workbench_server  # noqa: E402
from workbench.server import XLSX_NS, _read_xlsx_sheets, _valid_basic_auth, run_export  # noqa: E402


class ExportIntegrationTests(unittest.TestCase):
    def test_optional_basic_authentication(self):
        encoded = base64.b64encode("书库:correct-password".encode("utf-8")).decode("ascii")
        with patch.object(workbench_server, "AUTH_USERNAME", "书库"), patch.object(
            workbench_server, "AUTH_PASSWORD", "correct-password"
        ):
            self.assertTrue(_valid_basic_auth(f"Basic {encoded}"))
            self.assertFalse(_valid_basic_auth(None))
            self.assertFalse(_valid_basic_auth("Basic invalid"))

    def test_remote_export_ignores_browser_selected_host_directory(self):
        people = [
            {"name": "甲", "actual_hours": 40, "issued_hours": 33},
            {"name": "乙", "actual_hours": 26, "issued_hours": 33},
        ]
        with tempfile.TemporaryDirectory() as output_directory, tempfile.TemporaryDirectory() as requested_directory:
            with patch.object(workbench_server, "REMOTE_MODE", True), patch.object(
                workbench_server, "OUTPUTS", Path(output_directory)
            ):
                result = run_export(
                    "settlement",
                    {
                        "period_start": "2026-08-01",
                        "period_end": "2026-08-31",
                        "issued_cap": 33,
                        "people": people,
                        "transfers": [{"payer": "乙", "receiver": "甲", "hours": 7}],
                        "output_dir": requested_directory,
                    },
                )
                self.assertEqual(result["path"], "转账表_2026-08-01_2026-08-31.xlsx")
                self.assertTrue((Path(output_directory) / result["path"]).is_file())
                self.assertEqual(list(Path(requested_directory).iterdir()), [])

    def test_schedule_export_keeps_daily_staffing_override_and_all_shift_columns(self):
        payload = {
            "cycle": {"start_date": "2026-08-24", "end_date": "2026-08-24"},
            "days": [{"date": "2026-08-24", "label": "周一"}],
            "shifts": [
                {"id": "morning", "name": "早班", "duration_hours": 2, "required_people": 1},
                {"id": "afternoon", "name": "下午班", "duration_hours": 2, "required_people": 1},
                {"id": "evening", "name": "晚班", "duration_hours": 3, "required_people": 1},
                {"id": "night", "name": "夜班", "duration_hours": 1, "required_people": 1},
            ],
            "people": [{"name": name, "unavailable": []} for name in ["甲", "乙", "丙", "丁"]],
            "day_requirements": {"2026-08-24": {"morning": 3}},
        }
        generated = generate_schedule(payload)
        expected_morning = set(
            next(
                row["people"]
                for row in generated["schedule"]["assignments"]
                if row["shift_id"] == "morning"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            result = run_export(
                "schedule",
                {
                    "schedule": generated["schedule"],
                    "validation": {"ok": False, "errors": ["stale client value"]},
                    "output_dir": directory,
                },
            )
            path = Path(result["path"])
            self.assertTrue(path.is_file())
            with zipfile.ZipFile(path) as archive:
                root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            cell_values = {}
            for cell in root.findall(".//main:c", XLSX_NS):
                reference = cell.attrib.get("r", "")
                text = "".join(node.text or "" for node in cell.findall(".//main:t", XLSX_NS))
                cell_values[reference] = text
            self.assertEqual({cell_values.get("C3"), cell_values.get("C4"), cell_values.get("C5")}, expected_morning)
            formulas = [node.text or "" for node in root.findall(".//main:f", XLSX_NS)]
            self.assertTrue(any(re.fullmatch(r"SUM\(C\d+:F\d+\)", formula) for formula in formulas))
            first_sheet = _read_xlsx_sheets(path)[0]
            total_row = next(row for row in first_sheet if len(row) > 1 and row[1] == "合计")
            self.assertEqual(total_row[2:6], [3, 1, 1, 1])
            self.assertEqual(total_row[6:8], [6, 12])

    def test_export_recalculates_final_settlement_and_rejects_invalid_transfer(self):
        people = [
            {"name": "收款人", "actual_hours": 40, "issued_hours": 33},
            {"name": "付款人", "actual_hours": 26, "issued_hours": 33},
        ]
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "period_start": "2026-08-01",
                "period_end": "2026-08-31",
                "issued_cap": 33,
                "people": people,
                "settlement": {"people": [{"name": "伪造旧结果", "actual_hours": 999}]},
                "transfers": [{"payer": "付款人", "receiver": "收款人", "hours": 7}],
                "output_dir": directory,
            }
            result = run_export("settlement", payload)
            rows = _read_xlsx_sheets(Path(result["path"]))[0]
            flattened = [value for row in rows for value in row]
            self.assertIn("收款人", flattened)
            self.assertNotIn("伪造旧结果", flattened)
            self.assertTrue(result["download_url"].startswith("/api/download/"))

            payload["transfers"] = [{"payer": "付款人", "receiver": "收款人", "hours": 6}]
            with self.assertRaisesRegex(SettlementValidationError, "尚未通过"):
                run_export("settlement", payload)

    def test_unbalanced_draft_can_export_and_existing_file_is_not_overwritten(self):
        people = [
            {"name": "甲", "actual_hours": 70, "issued_hours": 40},
            {"name": "乙", "actual_hours": 20, "issued_hours": 35},
        ]
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "period_start": "2026-08-01",
                "period_end": "2026-08-24",
                "issued_cap": 40,
                "people": people,
                "transfers": [{"payer": "乙", "receiver": "甲", "hours": 15}],
                "draft": True,
                "output_dir": directory,
            }
            first = Path(run_export("settlement", payload)["path"])
            second = Path(run_export("settlement", payload)["path"])
            self.assertTrue(first.is_file())
            self.assertTrue(second.is_file())
            self.assertNotEqual(first, second)
            self.assertTrue(second.stem.endswith("_2"))


if __name__ == "__main__":
    unittest.main()
