#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${BOOK_WORKBENCH_PORT:-8765}"
cd "${SCRIPT_DIR}"
if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3，请先安装 Python 3。"
  exit 1
fi
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:${PORT}" >/dev/null 2>&1 &
fi
BOOK_WORKBENCH_PORT="${PORT}" python3 workbench/server.py
