(() => {
  const workerURL = new URL("./browser_worker.mjs", document.currentScript.src);
  let worker, nextId = 0;
  const pending = new Map();
  const urls = new Set();
  function status(message, failed = false) {
    const node = document.getElementById("runtimeStatus");
    if (!node) return;
    node.textContent = message;
    node.classList.toggle("warning", failed);
  }
  function stop(message) {
    worker?.terminate(); worker = null;
    for (const task of pending.values()) { clearTimeout(task.timer); task.reject(new Error(message)); }
    pending.clear(); status(message + "；点击重试可保留当前输入。", true);
    document.getElementById("retryRuntime")?.classList.remove("hidden");
  }
  function start() {
    worker = new Worker(workerURL, {type: "module"});
    worker.onerror = () => stop("计算组件加载失败，请检查网络后重试");
    worker.onmessage = ({data}) => {
      if (data.status) status(data.status);
      const task = pending.get(data.id);
      if (!task) return;
      clearTimeout(task.timer); pending.delete(data.id);
      if (data.error || data.result?.ok === false) {
        task.reject(new Error(data.error || data.result.error)); return;
      }
      const result = data.result;
      if (result.file_base64) {
        const bytes = Uint8Array.from(atob(result.file_base64), c => c.charCodeAt(0));
        result.download_url = URL.createObjectURL(new Blob([bytes], {type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}));
        urls.add(result.download_url); delete result.file_base64;
      }
      task.resolve(result);
    };
  }
  function request(path, payload = {}, file = null) {
    return new Promise((resolve, reject) => {
      if (!worker) start();
      const id = ++nextId;
      const timer = setTimeout(() => stop("计算等待超时，请重试"), 120000);
      pending.set(id, {resolve, reject, timer});
      worker.postMessage({id, path, payload, file}, file ? [file.bytes] : []);
    });
  }
  window.workbenchBackend = {
    request,
    async importFile(kind, file) {
      if (file.size > 20 * 1024 * 1024) throw new Error("文件不能超过 20 MB");
      return request(`/api/import/${kind}`, {}, {name: file.name, bytes: await file.arrayBuffer()});
    },
  };
  document.getElementById("retryRuntime")?.addEventListener("click", event => {
    event.target.classList.add("hidden");
    request("/api/health").catch(error => stop(error.message));
  });
  window.addEventListener("unload", () => {for (const url of urls) URL.revokeObjectURL(url);});
})();
