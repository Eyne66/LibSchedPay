#!/bin/zsh

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${BOOK_WORKBENCH_PORT:-8765}"
URL="http://127.0.0.1:${PORT}"
LOG_FILE="${APP_DIR}/workbench/runtime/server.log"

if ! command -v python3 >/dev/null 2>&1; then
  echo "这台电脑没有找到 python3。请先安装 Python 3，再双击此启动器。"
  exit 1
fi

if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
  open "${URL}"
  exit 0
fi

mkdir -p "${APP_DIR}/workbench/runtime"
cd "${APP_DIR}"
python3 workbench/server.py >"${LOG_FILE}" 2>&1 &
SERVER_PID=$!

for _ in {1..20}; do
  if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
    open "${URL}"
    wait "${SERVER_PID}"
    exit $?
  fi
  sleep 0.25
done

echo "书库工作台启动失败，请查看：${LOG_FILE}"
cat "${LOG_FILE}"
kill "${SERVER_PID}" 2>/dev/null
exit 1
