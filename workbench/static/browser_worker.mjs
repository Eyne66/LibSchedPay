// All business decisions are implemented by the repository's Python modules.
const runtimeURL = new URL("../vendor/pyodide/", import.meta.url).href;
let engine;
let queue = Promise.resolve();

async function initialize() {
  self.postMessage({status: "正在加载计算组件，首次打开需要一些时间…"});
  const {loadPyodide} = await import(`${runtimeURL}pyodide.mjs`);
  const py = await loadPyodide({indexURL: runtimeURL});
  const files = ["__init__.py", "schedule.py", "schedule_balance.py", "settlement.py", "xlsx_export.py", "table_import.py", "service.py", "browser_api.py"];
  py.FS.mkdirTree("/app/book_workbench");
  const sources = await Promise.all(files.map(async file => {
    const response = await fetch(new URL(`../python/book_workbench/${file}`, import.meta.url));
    if (!response.ok) throw new Error(`无法加载计算文件：${file}`);
    return [file, await response.text()];
  }));
  for (const [file, source] of sources) py.FS.writeFile(`/app/book_workbench/${file}`, source);
  py.runPython('import sys\nsys.path.insert(0, "/app")\nfrom book_workbench.browser_api import request_json');
  self.postMessage({status: "计算组件已就绪 · 数据仅在当前浏览器处理", ready: true});
  return py;
}

self.onmessage = event => {
  const {id, path, payload, file} = event.data;
  // Serialise access to Python globals and its in-memory filesystem.
  queue = queue.then(async () => {
    try {
      if (!engine) engine = initialize().catch(error => {engine = null; throw error;});
      const py = await engine;
      let input = payload || {};
      if (file) {
        const extension = file.name.split(".").pop().toLowerCase();
        if (!["xlsx", "csv", "json"].includes(extension)) throw new Error("只支持 .xlsx、.csv、.json 文件");
        const filename = `/tmp/upload_${id}.${extension}`;
        py.FS.writeFile(filename, new Uint8Array(file.bytes));
        input = {file_path: filename};
      }
      py.globals.set("request_path", path);
      py.globals.set("request_payload", JSON.stringify(input));
      const result = JSON.parse(py.runPython("request_json(request_path, request_payload)"));
      self.postMessage({id, result});
    } catch (error) {
      self.postMessage({id, error: error.message || "计算组件加载失败，请重试"});
    }
  });
};
