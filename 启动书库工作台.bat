@echo off
setlocal
cd /d "%~dp0"
set "PORT=%BOOK_WORKBENCH_PORT%"
if "%PORT%"=="" set "PORT=8765"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>nul
  if not %errorlevel%==0 (
    echo 未找到 Python 3，请先安装 Python 3。
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

start "书库工作台" "http://127.0.0.1:%PORT%"
%PYTHON% workbench\server.py
pause
