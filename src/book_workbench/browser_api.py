"""Browser adapter for the existing deterministic Python services.

No HTTP server, shell commands or AI calls. Temporary files live in the
browser worker's memory and are removed after each import/export.
"""
from __future__ import annotations

import base64
import json
import re
import tempfile
from pathlib import Path

from .schedule import generate_schedule, validate_schedule
from .settlement import calculate_settlement, validate_transfers
from .service import _validated_export_payload
from .table_import import parse_schedule_template, parse_uploaded_table
from .xlsx_export import export_payload


def dispatch(path, payload):
    if path == "/api/health":
        return {"ok": True, "remote_mode": True, "browser_runtime": True}
    if path == "/api/schedule/generate":
        return {"ok": True, **generate_schedule(payload)}
    if path == "/api/schedule/validate":
        return {"ok": True, "validation": validate_schedule(payload)}
    if path == "/api/settlement/calculate":
        return {"ok": True, "result": calculate_settlement(payload.get("people", []), payload["issued_cap"])}
    if path == "/api/settlement/validate-transfers":
        return {"ok": True, "result": validate_transfers(payload.get("people", []), payload.get("transfers", []), payload["issued_cap"])}
    if path.startswith("/api/import/"):
        kind = path.rsplit("/", 1)[-1]
        source = Path(payload["file_path"])
        try:
            result = parse_schedule_template(source) if kind == "schedule-template" else parse_uploaded_table(source, kind)
            return {"ok": True, **result}
        finally:
            source.unlink(missing_ok=True)
    if path.startswith("/api/export/"):
        kind = path.rsplit("/", 1)[-1].replace("-", "_")
        labels = {"schedule": "排班表", "settlement_summary": "实际工时统计表", "settlement": "工时转账表", "settlement_public": "工时转账公示表"}
        if kind not in labels:
            raise ValueError("未知的输出类型")
        checked = _validated_export_payload(kind, payload)
        start = payload.get("schedule", {}).get("cycle", {}).get("start_date", "") if kind == "schedule" else payload.get("period_start", "")
        end = payload.get("schedule", {}).get("cycle", {}).get("end_date", "") if kind == "schedule" else payload.get("period_end", "")
        suffix = "_草案" if payload.get("draft") else ""
        filename = re.sub(r'[/\\:*?"<>|]', "_", f"{labels[kind]}_{start}_{end}{suffix}.xlsx")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / filename
            export_payload(kind, checked, output)
            content = base64.b64encode(output.read_bytes()).decode("ascii")
        return {"ok": True, "path": filename, "file_base64": content}
    raise ValueError("未知操作")


def request_json(path, payload_json):
    try:
        result = dispatch(path, json.loads(payload_json))
    except (ValueError, TypeError, KeyError) as error:
        result = {"ok": False, "error": str(error)}
    return json.dumps(result, ensure_ascii=False)
