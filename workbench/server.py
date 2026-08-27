#!/usr/bin/env python3
"""Local, single-user web workbench for schedule and settlement tasks."""

from __future__ import annotations

import base64
import csv
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from book_workbench.schedule import ScheduleValidationError, generate_schedule, validate_schedule  # noqa: E402
from book_workbench.settlement import SettlementValidationError, calculate_settlement, validate_transfers  # noqa: E402
from book_workbench.xlsx_export import export_payload  # noqa: E402

RUNTIME = ROOT / "workbench" / "runtime"
OUTPUTS = ROOT / "outputs"
XLSX_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_REQUEST_BYTES = 20 * 1024 * 1024
DOWNLOADS: dict[str, Path] = {}
DOWNLOADS_LOCK = Lock()
REMOTE_MODE = os.environ.get("BOOK_WORKBENCH_REMOTE", "").strip().lower() in {"1", "true", "yes", "on"}
AUTH_USERNAME = os.environ.get("BOOK_WORKBENCH_USERNAME", "")
AUTH_PASSWORD = os.environ.get("BOOK_WORKBENCH_PASSWORD", "")


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def _valid_basic_auth(authorization: str | None) -> bool:
    """Validate optional deployment credentials without affecting local use."""

    if not AUTH_USERNAME and not AUTH_PASSWORD:
        return True
    if not AUTH_USERNAME or not AUTH_PASSWORD or not authorization:
        return False
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return hmac.compare_digest(username.encode("utf-8"), AUTH_USERNAME.encode("utf-8")) and hmac.compare_digest(
        password.encode("utf-8"), AUTH_PASSWORD.encode("utf-8")
    )


def _request_body(handler: BaseHTTPRequestHandler) -> bytes:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ValueError("请求长度不正确") from None
    if length < 0 or length > MAX_REQUEST_BYTES:
        raise ValueError("上传内容过大，单次最多20MB")
    return handler.rfile.read(length)


def _register_download(path: Path) -> str:
    token = secrets.token_urlsafe(18)
    with DOWNLOADS_LOCK:
        DOWNLOADS[token] = path.resolve()
        while len(DOWNLOADS) > 200:
            DOWNLOADS.pop(next(iter(DOWNLOADS)))
    return f"/api/download/{token}"


def _safe_filename_part(value: Any, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value or "")).strip(" ._")
    return (cleaned[:120] or fallback)


def _available_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("同名输出文件过多，请更换保存文件夹")


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


def parse_uploaded_table(path: Path, kind: str) -> dict[str, Any]:
    """Read a small user-provided CSV/JSON/XLSX file without changing it."""

    suffix = path.suffix.lower()
    rows: list[dict[str, Any]] = []
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("people", payload) if isinstance(payload, dict) else payload
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
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
            actual_key = next((key for key in row if "实际" in str(key) or "工时" in str(key) or str(key).lower() == "actual_hours"), None)
            issued_key = next((key for key in row if "下发" in str(key) or str(key).lower() == "issued_hours"), None)
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


def parse_payload(handler: BaseHTTPRequestHandler) -> Any:
    body = _request_body(handler)
    return json.loads(body.decode("utf-8"))


def parse_uploaded_file(handler: BaseHTTPRequestHandler) -> tuple[str, bytes]:
    """Parse one multipart file without the removed-in-Python-3.13 cgi module."""

    content_type = handler.headers.get("Content-Type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("上传请求必须使用 multipart/form-data")
    body = _request_body(handler)
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = BytesParser(policy=policy.default).parsebytes(header + body)
    if not message.is_multipart():
        raise ValueError("没有收到可识别的上传文件")
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data" or part.get_param("name", header="content-disposition") != "file":
            continue
        filename = Path(str(part.get_filename() or "")).name
        if not filename:
            raise ValueError("没有收到文件名")
        data = part.get_payload(decode=True) or b""
        if not data:
            raise ValueError("上传文件为空")
        return filename, data
    raise ValueError("没有收到文件")


def _validated_export_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Recalculate before export so stale browser state cannot become a final workbook."""

    checked = dict(payload)
    if kind == "schedule":
        schedule = payload.get("schedule") or {}
        validation = validate_schedule(schedule)
        if not validation.get("ok"):
            raise ScheduleValidationError("排班校验未通过：" + "；".join(validation.get("errors", [])))
        checked["validation"] = validation
    elif kind == "settlement_summary":
        people = payload.get("people") or []
        normalized = calculate_settlement(
            [
                {
                    "name": row.get("name"),
                    "actual_hours": row.get("actual_hours"),
                    "issued_hours": 0,
                }
                for row in people
                if isinstance(row, dict)
            ],
            issued_cap=0,
        )["people"]
        notes = {str(row.get("name", "")).strip(): row.get("notes", "") for row in people if isinstance(row, dict)}
        checked["people"] = [
            {"name": row["name"], "actual_hours": row["actual_hours"], "notes": notes.get(row["name"], "")}
            for row in normalized
        ]
    elif kind in {"settlement", "settlement_public"}:
        people = payload.get("people") or []
        issued_cap = payload.get("issued_cap", "33")
        settlement = calculate_settlement(people, issued_cap=issued_cap)
        transfers = payload.get("transfers") or []
        transfer_validation = validate_transfers(people, transfers, issued_cap=issued_cap)
        if kind == "settlement_public" or not payload.get("draft"):
            if not transfer_validation.get("ok"):
                raise SettlementValidationError(
                    "最终转账配平尚未通过：" + "；".join(transfer_validation.get("errors", []))
                )
        checked["settlement"] = settlement
        checked["transfers"] = transfers
        checked["transfer_validation"] = transfer_validation
    return checked


def run_export(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _validated_export_payload(kind, payload)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    # A browser connected over the internet must never be able to choose an
    # arbitrary directory on the host machine. Online users receive the file
    # through the authenticated download endpoint instead.
    output_dir = OUTPUTS if REMOTE_MODE else Path(str(payload.get("output_dir") or OUTPUTS)).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    token = next(tempfile._get_candidate_names())
    input_path = RUNTIME / f"{token}.json"
    if kind == "schedule":
        label = _safe_filename_part(payload.get("schedule", {}).get("cycle", {}).get("start_date"), "排班")
        output_path = output_dir / f"排班表_{label}.xlsx"
    elif kind == "settlement_summary":
        start = _safe_filename_part(payload.get("period_start"), "工时")
        end = _safe_filename_part(payload.get("period_end"), start)
        output_path = output_dir / f"实际工时一览_{start}_{end}.xlsx"
    elif kind == "settlement_public":
        start = _safe_filename_part(payload.get("period_start"), "工时")
        end = _safe_filename_part(payload.get("period_end"), start)
        output_path = output_dir / f"人工转账配平表_{start}_{end}.xlsx"
    else:
        start = payload.get("period_start")
        end = payload.get("period_end")
        label = _safe_filename_part(
            f"{start}_{end}" if start and end else payload.get("month"),
            "工时",
        )
        prefix = "转账核算草案" if payload.get("draft") else "转账表"
        output_path = output_dir / f"{prefix}_{label}.xlsx"
    output_path = _available_output_path(output_path)
    try:
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        export_payload(kind, payload, output_path)
    finally:
        input_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "path": output_path.name if REMOTE_MODE else str(output_path),
        "download_url": _register_download(output_path),
        "builder_output": "Python 标准库 XLSX 输出完成",
    }


def choose_output_directory() -> dict[str, Any]:
    """Use the native folder picker when the host system provides one."""

    if sys.platform == "darwin":
        script = 'POSIX path of (choose folder with prompt "选择书库工作台成品保存文件夹")'
        command = ["osascript", "-e", script]
    elif os.name == "nt":
        script = "Add-Type -AssemblyName System.Windows.Forms; $dialog=New-Object System.Windows.Forms.FolderBrowserDialog; if($dialog.ShowDialog() -eq 'OK'){[Console]::Write($dialog.SelectedPath)}"
        command = ["powershell", "-NoProfile", "-STA", "-Command", script]
    else:
        if shutil.which("zenity"):
            command = ["zenity", "--file-selection", "--directory", "--title=选择书库工作台成品保存文件夹"]
        elif shutil.which("kdialog"):
            command = ["kdialog", "--getexistingdirectory", str(OUTPUTS)]
        else:
            return {"ok": False, "cancelled": True, "error": "当前系统没有可用的文件夹选择器，请直接使用项目 outputs 文件夹。"}
    picked = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if picked.returncode != 0 or not picked.stdout.strip():
        return {"ok": False, "cancelled": True}
    return {"ok": True, "path": picked.stdout.strip()}


def reveal_output(output_path: Path) -> None:
    """Reveal an output file using the host system's file manager."""

    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(output_path)], check=False)
    elif os.name == "nt":
        subprocess.run(["explorer", "/select,", str(output_path)], check=False)
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(output_path.parent)], check=False)


class Handler(BaseHTTPRequestHandler):
    server_version = "BookWorkbench/0.4"

    def _send(
        self,
        status: int,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, "application/json; charset=utf-8", json_bytes(value))

    def _authorize(self) -> bool:
        if _valid_basic_auth(self.headers.get("Authorization")):
            return True
        self._send(
            401,
            "text/plain; charset=utf-8",
            "请输入书库工作台访问账号和密码。".encode("utf-8"),
            {"WWW-Authenticate": 'Basic realm="LibSchedPay", charset="UTF-8"'},
        )
        return False

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        if self.path.startswith("/api/download/"):
            token = self.path.rsplit("/", 1)[-1]
            with DOWNLOADS_LOCK:
                output_path = DOWNLOADS.get(token)
            if output_path is None or not output_path.is_file():
                self._json(404, {"ok": False, "error": "下载文件不存在或服务已重启"})
                return
            self._send(
                200,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                output_path.read_bytes(),
                {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(output_path.name)}"},
            )
            return
        if self.path == "/" or self.path == "/index.html":
            content = (ROOT / "workbench" / "static" / "index.html").read_bytes()
            self._send(200, "text/html; charset=utf-8", content)
            return
        if self.path == "/static/app.js":
            self._send(200, "text/javascript; charset=utf-8", (ROOT / "workbench" / "static" / "app.js").read_bytes())
            return
        if self.path == "/static/style.css":
            self._send(200, "text/css; charset=utf-8", (ROOT / "workbench" / "static" / "style.css").read_bytes())
            return
        if self.path == "/static/output.css":
            self._send(200, "text/css; charset=utf-8", (ROOT / "workbench" / "static" / "output.css").read_bytes())
            return
        if self.path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "app_id": "book-workbench",
                    "version": "0.4",
                    "remote_mode": REMOTE_MODE,
                    "local_file_actions": not REMOTE_MODE,
                },
            )
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        try:
            if self.path == "/api/choose-output-directory":
                if REMOTE_MODE:
                    self._json(403, {"ok": False, "error": "在线版请直接下载 Excel 到当前设备"})
                    return
                self._json(200, choose_output_directory())
                return
            if self.path == "/api/reveal-output":
                if REMOTE_MODE:
                    self._json(403, {"ok": False, "error": "在线版不能操作服务器的文件管理器"})
                    return
                payload = parse_payload(self)
                output_path = Path(str(payload.get("path") or "")).expanduser()
                if not output_path.exists():
                    raise ValueError("输出文件不存在")
                reveal_output(output_path)
                self._json(200, {"ok": True})
                return
            if self.path.startswith("/api/import/"):
                kind = self.path.rsplit("/", 1)[-1]
                filename, content = parse_uploaded_file(self)
                RUNTIME.mkdir(parents=True, exist_ok=True)
                suffix = Path(filename).suffix.lower()
                uploaded = RUNTIME / f"upload_{next(tempfile._get_candidate_names())}{suffix}"
                try:
                    uploaded.write_bytes(content)
                    if kind == "schedule-template":
                        result = parse_schedule_template(uploaded)
                    else:
                        result = parse_uploaded_table(uploaded, "settlement" if kind == "settlement" else "questionnaire")
                finally:
                    uploaded.unlink(missing_ok=True)
                self._json(200, {"ok": True, **result})
                return

            payload = parse_payload(self)
            if self.path == "/api/schedule/generate":
                self._json(200, {"ok": True, **generate_schedule(payload)})
                return
            if self.path == "/api/schedule/validate":
                self._json(200, {"ok": True, "validation": validate_schedule(payload)})
                return
            if self.path == "/api/settlement/calculate":
                cap = payload.get("issued_cap", "33")
                result = calculate_settlement(payload.get("people", []), issued_cap=cap)
                self._json(200, {"ok": True, "result": result})
                return
            if self.path == "/api/settlement/validate-transfers":
                result = validate_transfers(payload.get("people", []), payload.get("transfers", []), payload.get("issued_cap", "33"))
                self._json(200, {"ok": True, "result": result})
                return
            if self.path == "/api/export/schedule":
                self._json(200, run_export("schedule", payload))
                return
            if self.path == "/api/export/settlement":
                self._json(200, run_export("settlement", payload))
                return
            if self.path == "/api/export/settlement-summary":
                self._json(200, run_export("settlement_summary", payload))
                return
            if self.path == "/api/export/settlement-public":
                self._json(200, run_export("settlement_public", payload))
                return
            self._json(404, {"ok": False, "error": "not found"})
        except (ValueError, KeyError, ScheduleValidationError, SettlementValidationError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # Keep the UI from hiding export/runtime failures.
            self._json(500, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> int:
    host = os.environ.get("BOOK_WORKBENCH_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("BOOK_WORKBENCH_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Book Workbench running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
