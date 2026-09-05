"""Deterministic file imports shared by the local server and browser runtime."""
from __future__ import annotations
import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Any
XLSX_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def _cell_text(value: Any) -> str:
    return str(value or "").strip()


def _matrix_to_rows(matrix: list[list[Any]], kind: str) -> list[dict[str, Any]]:
    """Turn a worksheet matrix into records, including simple no-header tables.

    The workbench receives both exported tables with headers and hand-made
    vertical lists. We deliberately use a small set of known labels instead of
    asking an AI model to guess the meaning of every column.
    """

    matrix = [list(row) for row in matrix if any(value not in (None, "") for value in row)]
    if not matrix:
        return []

    header_index = None
    for index, row in enumerate(matrix[:10]):
        labels = [_cell_text(value).lower() for value in row]
        has_name = any("姓名" in label or label == "name" for label in labels)
        if kind == "settlement":
            has_actual = any("实际" in label or "工时" in label or label == "actual_hours" for label in labels)
            if has_name and has_actual:
                header_index = index
                break
        elif has_name:
            header_index = index
            break

    if header_index is not None:
        header_row = matrix[header_index]
        headers = [_cell_text(value) for value in header_row]
        _check_headers(headers)
        return [
            {
                headers[column]: json_safe(values[column]) if column < len(values) else None
                for column in range(len(headers))
                if headers[column]
            }
            for values in matrix[header_index + 1 :]
            if any(value not in (None, "") for value in values)
        ]

    # No header: a one-column sheet is a vertical name list. A two-column
    # settlement sheet is interpreted as name + actual hours in row order.
    if kind != "settlement":
        return [
            {"姓名": json_safe(row[0])}
            for row in matrix
            if row and row[0] not in (None, "")
        ]

    converted = []
    for row in matrix:
        if len(row) < 2 or row[0] in (None, "") or row[1] in (None, ""):
            continue
        item = {"姓名": json_safe(row[0]), "实际工时": json_safe(row[1])}
        if len(row) >= 3 and row[2] not in (None, ""):
            item["官方下发工时"] = json_safe(row[2])
        converted.append(item)
    return converted


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", XLSX_NS))
    raw = cell.findtext("main:v", default="", namespaces=XLSX_NS)
    if raw == "":
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (IndexError, ValueError):
            return raw
    if cell_type == "b":
        return raw == "1"
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def _xlsx_column_number(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        return 1
    value = 0
    for letter in letters.group(0):
        value = value * 26 + ord(letter) - 64
    return value


def _read_xlsx_sheets(path: Path) -> list[list[list[Any]]]:
    """Read worksheet matrices with only the Python standard library.

    This keeps the downloadable workbench independent from openpyxl, pip and
    any machine-specific Python environment. It supports the normal text and
    numeric cells used by questionnaire and attendance tables.
    """

    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("main:si", XLSX_NS):
                shared_strings.append("".join(node.text or "" for node in item.findall(".//main:t", XLSX_NS)))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {
            rel.attrib.get("Id"): rel.attrib.get("Target", "")
            for rel in rels
        }
        sheets: list[list[list[Any]]] = []
        for sheet in workbook.findall("main:sheets/main:sheet", XLSX_NS):
            target = rel_targets.get(sheet.attrib.get(f"{{{NS_REL}}}id"), "")
            if not target:
                continue
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            if target not in archive.namelist():
                continue
            root = ET.fromstring(archive.read(target))
            rows: list[list[Any]] = []
            for row in root.findall("main:sheetData/main:row", XLSX_NS):
                values: dict[int, Any] = {}
                for cell in row.findall("main:c", XLSX_NS):
                    column = _xlsx_column_number(cell.attrib.get("r", "A1"))
                    values[column] = _xlsx_cell_value(cell, shared_strings)
                if values:
                    last_column = max(values)
                    rows.append([values.get(column, "") for column in range(1, last_column + 1)])
            sheets.append(rows)
        return sheets


def _schedule_template_from_matrix(matrix: list[list[Any]]) -> dict[str, Any]:
    """Extract shift definitions and a roster from a finished schedule sheet.

    A finished workbook is used only as a structural reference. Existing
    assignments are deliberately not imported, so the next schedule still
    starts as a fresh, editable draft.
    """

    rows = [list(row) for row in matrix if any(value not in (None, "") for value in row)]
    if not rows:
        raise ValueError("成品排班表中没有可识别的数据")

    weekday_row_index = None
    weekday_columns: list[int] = []
    for index, row in enumerate(rows[:15]):
        columns = [
            column
            for column, value in enumerate(row)
            if re.search(r"(?:周|星期)[一二三四五六日天]", _cell_text(value))
        ]
        if len(columns) >= 2:
            weekday_row_index = index
            weekday_columns = columns
            break
    if weekday_row_index is None:
        raise ValueError("成品排班表中没有识别到周一至周日的日期列")
    weekday_labels = [_cell_text(rows[weekday_row_index][column]) for column in weekday_columns]

    summary_names: list[str] = []
    summary_header_index = None
    summary_name_column = None
    for index, row in enumerate(rows):
        for column, value in enumerate(row):
            if _cell_text(value) == "姓名":
                summary_header_index = index
                summary_name_column = column
                break
        if summary_header_index is not None:
            break
    if summary_header_index is not None and summary_name_column is not None:
        for row in rows[summary_header_index + 1 :]:
            if summary_name_column >= len(row):
                continue
            name = _cell_text(row[summary_name_column])
            if not name or name in {"合计", "总计"}:
                break
            if name not in summary_names:
                summary_names.append(name)

    name_identities = {"".join(name.split()) for name in summary_names}
    time_pattern = re.compile(r"(\d{1,2}:\d{2})\s*(?:-|—|–|到|至)\s*(\d{1,2}:\d{2})")
    shift_rows: list[tuple[int, str, str, str]] = []
    for index, row in enumerate(rows):
        text = " ".join(_cell_text(value) for value in row if _cell_text(value))
        match = time_pattern.search(text)
        if not match:
            continue
        if "上午" in text or "早班" in text or "早" in text:
            name = "早班"
        elif "下午" in text or "下午班" in text:
            name = "下午班"
        elif "晚上" in text or "晚班" in text or "晚" in text:
            name = "晚班"
        else:
            name = f"班次{len(shift_rows) + 1}"
        shift_rows.append((index, name, match.group(1), match.group(2)))

    if not shift_rows:
        raise ValueError("成品排班表中没有识别到班次时间，例如 9:00-11:00")

    shifts: list[dict[str, Any]] = []
    day_requirements_by_weekday: dict[str, dict[str, int]] = {}
    for shift_index, (row_index, name, start, end) in enumerate(shift_rows):
        end_row = shift_rows[shift_index + 1][0] if shift_index + 1 < len(shift_rows) else (
            summary_header_index if summary_header_index is not None else len(rows)
        )
        counts: list[int] = []
        for column in weekday_columns:
            count = 0
            for row in rows[row_index:end_row]:
                if column >= len(row):
                    continue
                value = _cell_text(row[column])
                if not value or re.search(r"\d+\s*人", value):
                    continue
                if name_identities and "".join(value.split()) not in name_identities:
                    continue
                count += 1
            counts.append(count)
        required_people = max(counts or [0])
        if required_people <= 0:
            raise ValueError(f"无法从成品排班表识别{name}的每班人数")
        shift_id = (
            ["morning", "afternoon", "evening"][shift_index]
            if shift_index < 3
            else f"shift_{shift_index + 1}"
        )
        for weekday, count in zip(weekday_labels, counts):
            if count != required_people:
                day_requirements_by_weekday.setdefault(weekday, {})[shift_id] = count
        start_minutes = sum(int(part) * factor for part, factor in zip(start.split(":"), (60, 1)))
        end_minutes = sum(int(part) * factor for part, factor in zip(end.split(":"), (60, 1)))
        duration_hours = (end_minutes - start_minutes) / 60
        if duration_hours <= 0:
            raise ValueError(f"{name}的班次时间不正确：{start}-{end}")
        shifts.append(
            {
                "id": shift_id,
                "name": name,
                "start": start,
                "end": end,
                "duration_hours": duration_hours,
                "required_people": required_people,
            }
        )

    if not summary_names:
        for row_index, _, _, _ in shift_rows:
            for row in rows[row_index:]:
                for column in weekday_columns:
                    value = _cell_text(row[column]) if column < len(row) else ""
                    if value and not re.search(r"\d+\s*人", value) and value not in summary_names:
                        summary_names.append(value)

    return {
        "kind": "schedule-template",
        "shifts": shifts,
        "people": [{"name": name, "unavailable_weekdays": [], "notes": []} for name in summary_names],
        "day_requirements_by_weekday": day_requirements_by_weekday,
        "count": len(summary_names),
    }


def parse_schedule_template(path: Path) -> dict[str, Any]:
    """Read shift structure and roster from a finished schedule workbook."""

    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        candidates = []
        for matrix in _read_xlsx_sheets(path):
            nonempty_cells = sum(1 for row in matrix for value in row if value not in (None, ""))
            if nonempty_cells:
                candidates.append((nonempty_cells, len(matrix), matrix))
        if not candidates:
            raise ValueError("成品排班表中没有可识别的数据")
        _, _, matrix = max(candidates, key=lambda item: (item[0], item[1]))
        return _schedule_template_from_matrix(matrix)
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return _schedule_template_from_matrix(list(csv.reader(handle)))
    raise ValueError("读取成品排班表只支持 .xlsx 或 .csv")



def _header_key(value):
    return "".join(str(value).split()).lower()

def _check_headers(headers):
    keys = [_header_key(h) for h in headers if str(h).strip()]
    if len(keys) != len(set(keys)):
        raise ValueError("表头中有重复列，请保留唯一的姓名、实际工时和下发工时列")

def _column(row, aliases, label, required=False):
    matches = [key for key in row if _header_key(key) in aliases]
    if len(matches) > 1:
        raise ValueError(f"{label}对应多个列，请只保留一列")
    if not matches and required:
        raise ValueError(f"没有识别到{label}列，请核对表头")
    return matches[0] if matches else None

def parse_uploaded_table(path: Path, kind: str) -> dict[str, Any]:
    """Read a small user-provided CSV/JSON/XLSX file without changing it."""

    suffix = path.suffix.lower()
    rows: list[dict[str, Any]] = []
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("people", payload) if isinstance(payload, dict) else payload
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            _check_headers(reader.fieldnames or [])
            rows = list(reader)
    elif suffix == ".xlsx":
        # Do not assume the workbook's active sheet is the data sheet. Some
        # exports contain a nearly-empty cover sheet or have stale dimension
        # metadata. Choose the sheet with the most populated cells, then parse
        # headers or a simple vertical list deterministically.
        candidates = []
        for matrix in _read_xlsx_sheets(path):
            nonempty_cells = sum(1 for row in matrix for value in row if value not in (None, ""))
            if nonempty_cells:
                candidates.append((nonempty_cells, len(matrix), matrix))
        if candidates:
            _, _, matrix = max(candidates, key=lambda item: (item[0], item[1]))
            rows = _matrix_to_rows(matrix, kind)
    else:
        raise ValueError("只支持 .xlsx、.csv、.json 文件")

    if not isinstance(rows, list):
        raise ValueError("上传文件中没有可识别的表格数据")
    if kind == "settlement":
        converted = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name_key = next((key for key in row if "姓名" in str(key) or str(key).lower() == "name"), None)
            actual_key = _column(row, {"实际工时", "实际工作工时", "actual_hours", "工时"}, "实际工时", required=True)
            issued_key = _column(row, {"下发工时", "官方下发工时", "issued_hours"}, "官方下发工时")
            if name_key is None or actual_key is None:
                continue
            raw_name = row[name_key]
            if raw_name in (None, "") or str(raw_name).strip().lower() in {"none", "合计", "总计"}:
                continue
            item: dict[str, Any] = {"name": str(raw_name).strip(), "actual_hours": row[actual_key]}
            if issued_key is not None and row[issued_key] not in (None, ""):
                item["issued_hours"] = row[issued_key]
            converted.append(item)
        if not converted:
            raise ValueError("没有识别到“姓名”和“实际工时”列")
        return {"kind": kind, "rows": converted, "count": len(converted)}
    # For questionnaire files, also expose only unambiguous structured
    # constraints. Free-text interpretations remain notes for confirmation.
    normalized_people = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name_key = next((key for key in row if "姓名" in str(key) or str(key).lower() == "name"), None)
        if name_key is None or row[name_key] in (None, ""):
            continue
        name = str(row[name_key]).strip()
        unavailable = []
        notes = []
        slot_headers = {"9-11": "morning", "14-16": "afternoon", "19-22": "evening"}
        for key, value in row.items():
            text = str(value or "").strip()
            if not text:
                continue
            header = str(key)
            matched_shift = next((shift_id for label, shift_id in slot_headers.items() if label in header), None)
            if matched_shift and "补充内容" in header:
                weekdays = re.findall(r"周[一二三四五六日天]", text)
                for weekday in weekdays:
                    unavailable.append({"weekday": weekday, "shift_id": matched_shift, "source": text})
            elif header not in {str(name_key), "编号", "提交人", "提交时间", "智能总结"}:
                notes.append(f"{header}：{text}")
        normalized_people.append({"name": name, "unavailable_weekdays": unavailable, "notes": notes})
    return {"kind": kind, "rows": rows, "people": normalized_people, "count": len(normalized_people)}
