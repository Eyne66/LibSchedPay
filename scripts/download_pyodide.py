"""Fetch the exact, checksum-verified browser runtime used by LibSchedPay.

Uses Python's standard library. Does not install anything system-wide.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "pyodide-runtime.lock.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_runtime(directory: Path) -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    for entry in lock["files"]:
        path = directory / entry["name"]
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise SystemExit(f"计算组件缺失或校验失败：{entry['name']}。请先运行 python scripts/download_pyodide.py")


def main() -> None:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    directory = ROOT / "dist" / "vendor" / "pyodide"
    directory.mkdir(parents=True, exist_ok=True)
    for entry in lock["files"]:
        destination = directory / entry["name"]
        if destination.is_file() and sha256(destination) == entry["sha256"]:
            print(f"Verified cached {entry['name']}", flush=True)
            continue
        for attempt in range(3):
            try:
                request = Request(entry["url"], headers={"User-Agent": "LibSchedPay-runtime-setup"})
                with urlopen(request, timeout=30) as response:
                    content = response.read()
                break
            except OSError as error:
                if attempt == 2:
                    raise SystemExit(f"下载失败：{entry['name']}。请检查网络后重试：{error}") from error
                time.sleep(attempt + 1)
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise SystemExit(f"下载内容与锁定版本不符：{entry['name']}。已停止，不会使用未知版本。")
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
        print(f"Downloaded and verified {entry['name']} ({len(content)} bytes)", flush=True)
    (directory / "NOTICE.txt").write_text((ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"), encoding="utf-8")
    verify_runtime(directory)
    print(f"Pyodide {lock['version']} ready.")


if __name__ == "__main__":
    main()
