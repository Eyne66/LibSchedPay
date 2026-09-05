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
from book_workbench.table_import import (json_safe, _cell_text, _matrix_to_rows, _xlsx_cell_value, _xlsx_column_number, _read_xlsx_sheets, _schedule_template_from_matrix, parse_schedule_template, parse_uploaded_table)
from book_workbench.service import _validated_export_payload
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
