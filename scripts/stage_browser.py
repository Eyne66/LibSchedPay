"""Stage the shared source as a self-contained static website."""
from pathlib import Path
import shutil
from download_pyodide import verify_runtime

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
verify_runtime(DIST / "vendor" / "pyodide")
static = DIST / "static"
python = DIST / "python" / "book_workbench"
static.mkdir(parents=True, exist_ok=True)
python.mkdir(parents=True, exist_ok=True)
for source in (ROOT / "workbench" / "static").iterdir():
    if source.suffix in {".js", ".mjs", ".css"}:
        shutil.copyfile(source, static / source.name)
for source in (ROOT / "src" / "book_workbench").glob("*.py"):
    shutil.copyfile(source, python / source.name)
html = (ROOT / "workbench" / "static" / "index.html").read_text(encoding="utf-8")
html = html.replace('<section class="conversation-card">', '<div class="runtime-bar"><span id="runtimeStatus" role="status">正在准备计算组件…</span><button id="retryRuntime" class="ghost-button hidden">重试加载</button></div><section class="conversation-card">')
html = html.replace('<script src="/static/app.js">', '<script src="/static/browser_backend.js"></script>\n  <script src="/static/app.js">')
html = html.replace('输入数据不会展示给其他访问者。', '数据在当前浏览器处理，不上传到共享数据库。离开或刷新前请下载所需表格。')
html = html.replace('src="/static/', 'src="./static/').replace('href="/static/', 'href="./static/')
(DIST / "index.html").write_text(html, encoding="utf-8")
(DIST / ".nojekyll").write_text("", encoding="utf-8")
print("Static site staged from the shared source.")
