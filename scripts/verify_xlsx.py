#!/usr/bin/env python3
"""Check that XLSX files contain readable workbook and worksheet parts."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def verify(path: Path) -> None:
    required = {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml"}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = required - names
        if missing:
            raise ValueError(f"缺少 XLSX 文件部件：{', '.join(sorted(missing))}")
        ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = sorted(name for name in names if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        if not sheets:
            raise ValueError("XLSX 中没有工作表")
        for sheet in sheets:
            ET.fromstring(archive.read(sheet))
    print(f"OK  {path}  ({len(sheets)} worksheets)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法：python3 scripts/verify_xlsx.py 文件.xlsx [文件.xlsx ...]")
    try:
        for item in sys.argv[1:]:
            verify(Path(item))
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
