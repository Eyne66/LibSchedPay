"""Small dependency-free XLSX writer used by the local workbench.

The first prototype used a desktop-only Node package to create Excel files.
That made the folder impossible to send to another computer.  This module
writes the small set of XLSX XML parts needed by the workbench with Python's
standard library only.  The calculation logic remains in the separate core
modules; this file is only presentation/export code.
"""

from __future__ import annotations

import math
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def col_name(index: int) -> str:
    """Return a 1-based column number as an Excel column name."""

    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def as_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def display_number(value: Any) -> str:
    number = as_number(value)
    if number is None:
        return str(value or "")
    return str(number)


def period_label(payload: dict[str, Any]) -> str:
    if payload.get("period_start") and payload.get("period_end"):
        return f"{payload['period_start']}—{payload['period_end']}"
    return str(payload.get("month") or "")


def public_period_label(payload: dict[str, Any]) -> str:
    start = str(payload.get("period_start") or "").strip()
    end = str(payload.get("period_end") or "").strip()
    if not start or not end:
        return str(payload.get("month") or "")
    match_start = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", start)
    match_end = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", end)
    if not match_start or not match_end:
        return period_label(payload)
    start_year, start_month, start_day = match_start.groups()
    end_year, end_month, end_day = match_end.groups()
    if start_year == end_year and start_month == end_month and start_day == "01":
        next_month = int(start_month) % 12 + 1
        next_year = int(start_year) + (1 if int(start_month) == 12 else 0)
        last_day = (date(next_year, next_month, 1).toordinal() - date(int(start_year), int(start_month), 1).toordinal())
        if int(end_day) == last_day:
            return f"{int(start_month)}月"
    if start_year == end_year and start_month == end_month:
        return f"{int(start_month)}月{int(start_day)}日—{int(end_day)}日"
    return f"{start_year}年{int(start_month)}月{int(start_day)}日—{end_year}年{int(end_month)}月{int(end_day)}日"


@dataclass
class Cell:
    value: Any = ""
    style: int = 0
    formula: str | None = None
    cached: Any = None


@dataclass
class Sheet:
    title: str
    cells: dict[tuple[int, int], Cell] = field(default_factory=dict)
    merges: list[str] = field(default_factory=list)
    widths: dict[int, float] = field(default_factory=dict)
    heights: dict[int, float] = field(default_factory=dict)
    freeze_rows: int = 0
    show_gridlines: bool = True

    def set(self, row: int, column: int, value: Any = "", style: int = 0, formula: str | None = None, cached: Any = None) -> None:
        self.cells[(row, column)] = Cell(value=value, style=style, formula=formula, cached=cached)

    def set_row(self, row: int, values: list[Any], style: int = 0) -> None:
        for column, value in enumerate(values, start=1):
            self.set(row, column, value, style=style)

    def merge(self, start_row: int, start_column: int, end_row: int, end_column: int) -> None:
        self.merges.append(f"{col_name(start_column)}{start_row}:{col_name(end_column)}{end_row}")


def _text_xml(value: Any) -> str:
    text = "" if value is None else str(value)
    preserve = text[:1].isspace() or text[-1:].isspace() or "\n" in text
    space = ' xml:space="preserve"' if preserve else ""
    return f"<is><t{space}>{escape(text)}</t></is>"


def _cell_xml(row: int, column: int, cell: Cell) -> str:
    ref = f"{col_name(column)}{row}"
    style = f' s="{cell.style}"' if cell.style else ""
    if cell.formula is not None:
        cached = cell.cached if cell.cached is not None else cell.value
        numeric = as_number(cached)
        if numeric is not None:
            return f'<c r="{ref}"{style}><f>{escape(str(cell.formula))}</f><v>{numeric}</v></c>'
        return f'<c r="{ref}" t="str"{style}><f>{escape(str(cell.formula))}</f><v>{escape(str(cached or ""))}</v></c>'
    numeric = as_number(cell.value)
    if numeric is not None:
        return f'<c r="{ref}"{style}><v>{numeric}</v></c>'
    if cell.value in (None, ""):
        return ""
    return f'<c r="{ref}" t="inlineStr"{style}>{_text_xml(cell.value)}</c>'


def _sheet_xml(sheet: Sheet) -> str:
    if sheet.cells:
        max_row = max(row for row, _ in sheet.cells)
        max_col = max(column for _, column in sheet.cells)
    else:
        max_row = max_col = 1
    dimension = f"A1:{col_name(max_col)}{max_row}"
    parts = [f'<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">']
    parts.append(f'<dimension ref="{dimension}"/>')
    parts.append('<sheetViews>')
    if sheet.freeze_rows:
        top = sheet.freeze_rows + 1
        parts.append(f'<sheetView showGridLines="{"1" if sheet.show_gridlines else "0"}" workbookViewId="0"><pane ySplit="{sheet.freeze_rows}" topLeftCell="A{top}" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="A{top}" sqref="A{top}"/></sheetView>')
    else:
        parts.append(f'<sheetView showGridLines="{"1" if sheet.show_gridlines else "0"}" workbookViewId="0"/>')
    parts.append('</sheetViews>')
    parts.append('<sheetFormatPr defaultRowHeight="18"/>')
    if sheet.widths:
        parts.append('<cols>')
        for column, width in sorted(sheet.widths.items()):
            parts.append(f'<col min="{column}" max="{column}" width="{width}" customWidth="1"/>')
        parts.append('</cols>')
    parts.append('<sheetData>')
    for row in range(1, max_row + 1):
        row_cells = [_cell_xml(row, column, sheet.cells[(row, column)]) for column in range(1, max_col + 1) if (row, column) in sheet.cells]
        row_cells = [item for item in row_cells if item]
        height = f' ht="{sheet.heights[row]}" customHeight="1"' if row in sheet.heights else ""
        if row_cells:
            parts.append(f'<row r="{row}"{height}>{"".join(row_cells)}</row>')
    parts.append('</sheetData>')
    if sheet.merges:
        parts.append(f'<mergeCells count="{len(sheet.merges)}">{"".join(f"<mergeCell ref={quoteattr(item)}/>" for item in sheet.merges)}</mergeCells>')
    parts.append('</worksheet>')
    return "".join(parts)


def _styles_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{NS_MAIN}">
  <numFmts count="0"/>
  <fonts count="6">
    <font><sz val="10"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="16"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FF183B56"/><sz val="10"/><name val="Calibri"/><family val="2"/></font>
    <font><color rgb="FF1D2939"/><sz val="10"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FF30C0B4"/><sz val="20"/><name val="华文中宋"/></font>
    <font><color rgb="FF000000"/><sz val="28"/><name val="华文中宋"/></font>
  </fonts>
  <fills count="7">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF183B56"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE8F1FB"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFF4B8"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE8F5EF"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFD3F4F1"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="3">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFD6DEE8"/></left><right style="thin"><color rgb="FFD6DEE8"/></right><top style="thin"><color rgb="FFD6DEE8"/></top><bottom style="thin"><color rgb="FFD6DEE8"/></bottom><diagonal/></border>
    <border><left style="thin"><color rgb="FFA8E9E4"/></left><right style="thin"><color rgb="FFA8E9E4"/></right><top style="thin"><color rgb="FFA8E9E4"/></top><bottom style="thin"><color rgb="FFA8E9E4"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="10">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="1" applyAlignment="1"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="4" borderId="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="3" fillId="5" borderId="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="4" fillId="0" borderId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="5" fillId="0" borderId="2" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="5" fillId="6" borderId="2" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="0"/><tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleMedium9"/>
</styleSheet>'''


def _content_types(sheet_count: int) -> str:
    overrides = "".join(f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for index in range(1, sheet_count + 1))
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  {overrides}
</Types>'''


def _workbook_xml(sheets: list[Sheet]) -> str:
    entries = "".join(f'<sheet name={quoteattr(sheet.title)} sheetId="{index}" r:id="rId{index}"/>' for index, sheet in enumerate(sheets, start=1))
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}"><sheets>{entries}</sheets><calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1"/></workbook>'''


def _workbook_rels(sheets: list[Sheet]) -> str:
    sheet_rels = "".join(f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>' for index in range(1, len(sheets) + 1))
    styles_id = len(sheets) + 1
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{NS_PKG_REL}">{sheet_rels}<Relationship Id="rId{styles_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''


def _root_rels() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{NS_PKG_REL}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''


def export_workbook(sheets: list[Sheet], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    app = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>书库工作台</Application><AppVersion>1.0</AppVersion></Properties>'''
    core = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>书库工作台</dc:creator><cp:lastModifiedBy>书库工作台</cp:lastModifiedBy><dcterms:created xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>'''
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("docProps/app.xml", app)
        archive.writestr("docProps/core.xml", core)
        archive.writestr("xl/workbook.xml", _workbook_xml(sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(sheets))
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, sheet in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheet))
    return path


def add_public_settlement_sheet(sheet: Sheet, payload: dict[str, Any]) -> None:
    transfers = payload.get("transfers") or payload.get("settlement", {}).get("transfers", [])
    groups: list[dict[str, Any]] = []
    by_receiver: dict[str, dict[str, Any]] = {}
    for transfer in transfers:
        payer = str(transfer.get("payer") or "").strip()
        receiver = str(transfer.get("receiver") or "").strip()
        hours = as_number(transfer.get("hours"))
        if not payer or not receiver or hours is None or hours <= 0:
            continue
        group = by_receiver.get(receiver)
        if group is None:
            group = {"receiver": receiver, "total": 0, "items": []}
            by_receiver[receiver] = group
            groups.append(group)
        group["total"] = Decimal(str(group["total"])) + Decimal(str(hours))
        group["items"].append((payer, hours))

    sheet.show_gridlines = False
    sheet.merge(1, 1, 1, 2)
    sheet.set(1, 1, f"工时转账表{public_period_label(payload)}", style=7)
    sheet.heights[1] = 46
    if not groups:
        sheet.merge(2, 1, 2, 2)
        sheet.set(2, 1, "暂无人工转账配平记录", style=8)
        sheet.heights[2] = 42
    else:
        row = 2
        for group in groups:
            start = row
            for index, (payer, hours) in enumerate(group["items"]):
                sheet.set(row, 1, f"{group['receiver']}{display_number(group['total'])}" if index == 0 else "", style=8)
                sheet.set(row, 2, f"{payer}-{display_number(hours)}", style=9)
                sheet.heights[row] = 44
                row += 1
            if row - start > 1:
                sheet.merge(start, 1, row - 1, 1)
    sheet.widths[1] = 30
    sheet.widths[2] = 30


def add_settlement_summary_sheet(sheet: Sheet, payload: dict[str, Any]) -> None:
    people = payload.get("people", [])
    sheet.show_gridlines = False
    sheet.merge(1, 1, 1, 4)
    sheet.set(1, 1, f"实际到岗工时一览 {period_label(payload)}", style=1)
    sheet.set_row(2, ["序号", "姓名", "实际工时", "备注"], style=2)
    for index, person in enumerate(people, start=1):
        sheet.set_row(index + 2, [index, person.get("name", ""), as_number(person.get("actual_hours")), person.get("notes", "")], style=3)
    total = len(people) + 3
    sheet.set_row(total, ["合计", "", "", ""], style=6)
    sheet.set(total, 3, "", style=6, formula=f"SUM(C3:C{total - 1})", cached=as_number(sum((Decimal(str(row.get("actual_hours"))) for row in people), Decimal("0"))))
    sheet.widths.update({1: 10, 2: 22, 3: 16, 4: 28})
    sheet.freeze_rows = 2


def add_schedule_sheets(schedule: dict[str, Any], validation: dict[str, Any]) -> list[Sheet]:
    sheet = Sheet("排班表", show_gridlines=False)
    record = Sheet("记录", show_gridlines=False)
    days = schedule.get("days", [])
    shifts = schedule.get("shifts", [])
    assignments = {(row.get("date"), row.get("shift_id")): row.get("people", []) for row in schedule.get("assignments", [])}
    day_requirements = schedule.get("day_requirements") or {}
    staffing_counts = [int(shift.get("required_people") or 0) for shift in shifts]
    staffing_counts.extend(
        int(required)
        for overrides in day_requirements.values()
        if isinstance(overrides, dict)
        for required in overrides.values()
    )
    max_rows = max([1, *staffing_counts])
    summary_end_col = len(shifts) + 6
    end_col = max(2 + max(len(days), 1), summary_end_col)
    sheet.merge(1, 2, 1, end_col)
    sheet.set(1, 2, f"书库排班表 {schedule.get('cycle', {}).get('start_date', '')}—{schedule.get('cycle', {}).get('end_date', '')}", style=1)
    sheet.set_row(2, ["", "班次"] + [day.get("label") or day.get("date", "") for day in days], style=2)
    record_rows: list[list[Any]] = []
    row = 3
    for shift in shifts:
        start = row
        for slot in range(max_rows):
            values = ["", f"{shift.get('name') or shift.get('id')}\n{shift.get('start', '')}–{shift.get('end', '')}\n{shift.get('duration_hours')}小时" if slot == 0 else ""]
            for day in days:
                names = assignments.get((day.get("date"), shift.get("id")), [])
                person = names[slot] if slot < len(names) else ""
                values.append(person)
                if person:
                    record_rows.append([day.get("date", ""), shift.get("name") or shift.get("id"), person, as_number(shift.get("duration_hours"))])
            sheet.set_row(row, values, style=5 if slot == 0 else 4)
            row += 1
        sheet.merge(start, 2, row - 1, 2)
    if not shifts:
        row = 3
    summary_start = row + 2
    names = list(dict.fromkeys(person.get("name") for person in schedule.get("people", []) if person.get("name")))
    shift_names = [shift.get("name") or shift.get("id") for shift in shifts]
    sheet.set_row(summary_start, ["", "姓名", *shift_names, "总班次", "总时长(h)", "状态", "备注"], style=2)
    total_shifts_column = len(shifts) + 3
    total_hours_column = len(shifts) + 4
    for index, name in enumerate(names, start=1):
        r = summary_start + index
        rows_for_person = [row_data for row_data in record_rows if row_data[2] == name]
        counts = [sum(1 for row_data in rows_for_person if row_data[1] == shift_name) for shift_name in shift_names]
        total_hours = sum((row_data[3] or 0 for row_data in rows_for_person), 0)
        sheet.set_row(r, ["", name, *counts, "", "", "待确认", ""], style=3)
        first_shift_column = 3
        last_shift_column = max(first_shift_column, len(shifts) + 2)
        sheet.set(
            r,
            total_shifts_column,
            "",
            style=3,
            formula=f"SUM({col_name(first_shift_column)}{r}:{col_name(last_shift_column)}{r})",
            cached=sum(counts),
        )
        sheet.set(
            r,
            total_hours_column,
            "",
            style=3,
            formula=f"SUMIFS('记录'!$D$2:$D${max(2, len(record_rows) + 1)},'记录'!$C$2:$C${max(2, len(record_rows) + 1)},$B{r})",
            cached=total_hours,
        )
    summary_total = summary_start + len(names) + 1
    sheet.set_row(
        summary_total,
        ["", "合计", *([""] * len(shifts)), "", "", "通过" if not validation.get("warnings") else "有提示", "；".join(validation.get("warnings", []))],
        style=6,
    )
    for column in range(3, total_hours_column + 1):
        letter = col_name(column)
        cached = 0
        for r in range(summary_start + 1, summary_total):
            cell = sheet.cells.get((r, column), Cell())
            source_value = cell.cached if cell.cached is not None else cell.value
            cached += as_number(source_value) or 0
        sheet.set(summary_total, column, "", style=6, formula=f"SUM({letter}{summary_start + 1}:{letter}{summary_total - 1})", cached=cached)
    record.set_row(1, ["日期", "班次", "姓名", "时长(h)"], style=2)
    for index, values in enumerate(record_rows, start=2):
        record.set_row(index, values, style=3)
    sheet.widths[2] = 22
    for column in range(3, 3 + len(days)):
        sheet.widths[column] = 15
    for column in range(3, total_shifts_column):
        sheet.widths[column] = max(sheet.widths.get(column, 0), 12)
    sheet.widths[total_shifts_column] = 14
    sheet.widths[total_hours_column] = 16
    sheet.widths[total_hours_column + 1] = 14
    sheet.widths[total_hours_column + 2] = 28
    for column in range(1, 5):
        record.widths[column] = 18
    sheet.freeze_rows = 2
    requirements = Sheet("岗位需求", show_gridlines=False)
    requirements.set_row(1, ["日期", "星期", "班次", "开始", "结束", "单次工时", "需要人数"], style=2)
    for index, (day, shift) in enumerate(((day, shift) for day in days for shift in shifts), start=2):
        required = day_requirements.get(day["date"], {}).get(shift["id"], shift["required_people"])
        requirements.set_row(index, [day["date"], day.get("label", ""), shift.get("name", shift["id"]), shift.get("start", ""), shift.get("end", ""), as_number(shift["duration_hours"]), required], style=3)
    requirements.widths.update({1: 18, 2: 25, 3: 16, 4: 14, 5: 14, 6: 14, 7: 14})
    requirements.freeze_rows = 1
    return [sheet, record, requirements]


def add_settlement_sheets(payload: dict[str, Any]) -> list[Sheet]:
    result = payload.get("settlement") or {}
    people = result.get("people", [])
    sheet = Sheet("差值明细", show_gridlines=False)
    sheet.merge(1, 1, 1, 6)
    sheet.set(1, 1, f"工时核算 {period_label(payload)}", style=1)
    sheet.set_row(2, ["姓名", "实际工时", "官方下发工时", "差值", "状态", "说明"], style=2)
    for index, person in enumerate(people, start=3):
        actual = as_number(person.get("actual_hours")) or 0
        issued = as_number(person.get("issued_hours")) or 0
        difference = as_number(person.get("difference_hours")) or 0
        status = "应收" if difference > 0 else ("应转出" if difference < 0 else "无差额")
        sheet.set_row(index, [person.get("name", ""), actual, issued, difference, status, ""], style=3)
        sheet.set(index, 4, "", style=3, formula=f"B{index}-C{index}", cached=difference)
        sheet.set(index, 5, "", style=3, formula=f'IF(D{index}>0,"应收",IF(D{index}<0,"应转出","无差额"))', cached=status)
    total = len(people) + 3
    totals = result.get("totals", {})
    sheet.set_row(total, ["合计", "", "", "", "", f"未配平差额：{totals.get('external_adjustment_hours', '')}"], style=6)
    for column, letter, key in ((2, "B", "actual_hours"), (3, "C", "issued_hours"), (4, "D", "difference_hours")):
        sheet.set(total, column, "", style=6, formula=f"SUM({letter}3:{letter}{total - 1})", cached=as_number(totals.get(key)) or 0)
    sheet.widths.update({1: 22, 2: 18, 3: 20, 4: 14, 5: 14, 6: 28})
    sheet.freeze_rows = 2

    public = Sheet("转账公示", show_gridlines=False)
    add_public_settlement_sheet(public, payload)
    check = Sheet("校验", show_gridlines=False)
    check.set_row(1, ["校验项", "结果"], style=2)
    check.set_row(2, ["实际工时总额", as_number(totals.get("actual_hours"))], style=3)
    check.set_row(3, ["官方下发总额", as_number(totals.get("issued_hours"))], style=3)
    check.set_row(4, ["总差额", as_number(totals.get("difference_hours"))], style=3)
    check.set_row(5, ["可配对转账工时", as_number(totals.get("draft_transfer_hours"))], style=3)
    check.set_row(6, ["未配平差额", as_number(totals.get("external_adjustment_hours"))], style=3)
    check.set_row(7, ["说明", "已平衡" if result.get("checks", {}).get("net_difference_is_zero") else "存在外部差额，请人工确认"], style=3)
    transfer_validation = payload.get("transfer_validation") or {}
    if transfer_validation:
        check.set_row(8, ["人工转账配平", "通过" if transfer_validation.get("ok") else "未完成"], style=3)
        errors = "；".join(str(error) for error in transfer_validation.get("errors", []))
        check.set_row(9, ["配平说明", errors or "无"], style=3)
    check.widths.update({1: 28, 2: 28})
    return [sheet, public, check]


def export_payload(kind: str, payload: dict[str, Any], output_path: str | Path) -> Path:
    if kind == "schedule":
        sheets = add_schedule_sheets(payload.get("schedule", {}), payload.get("validation", {}))
    elif kind == "settlement_summary":
        sheets = [Sheet("实际工时一览")]
        add_settlement_summary_sheet(sheets[0], payload)
    elif kind == "settlement_public":
        sheets = [Sheet("人工转账配平表")]
        add_public_settlement_sheet(sheets[0], payload)
    else:
        sheets = add_settlement_sheets(payload)
    return export_workbook(sheets, output_path)
