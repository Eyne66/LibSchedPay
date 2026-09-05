# LibSchedPay 复现与部署指南

[在线试用](https://libschedpay.bouncy-wren-3789.chatgpt.site) · [返回 README](README.md)

这个仓库包含可复现的网页程序、原 Python 计算核心、固定运行组件版本和回归测试。
下载者无需使用原作者的 ChatGPT 账号、托管项目编号或 AI API Key。

**是否必须改写成 JavaScript 才能部署？** 不需要。本项目的网页交互使用 JavaScript，排班、姓名校验、精确工时计算和 Excel 仍使用 `src/book_workbench` 中的 Python。静态版通过 Pyodide 在浏览器 Worker 里运行它，本地服务也调用相同核心。

如果另一个 Agent 接手，请先运行本文构建命令，不要只把 `workbench/static` 上传出去，也不要因为托管平台没有 Python 服务就直接重写计算。改写语言本身不保证功能等价，尤其需要保留小数精度、约束与导出回归。

## 1. 获取源码

可以在 GitHub 点击 **Code → Download ZIP**，下载并解压；也可以使用 Git：

```bash
git clone https://github.com/Eyne66/LibSchedPay.git
cd LibSchedPay
```

如果仓库处于 Private，只有获得仓库访问权限的人能下载。公开分享前，仓库所有者需要在
**Settings → General → Danger Zone → Change repository visibility** 中选择 **Public**。
这会公开整个仓库及提交历史。网页的公开访问与源码仓库是否公开是两个设置。

## 2. 生成并在本机运行网页版

准备 Python 3.10 或更高版本。使用标准库，不需要 `pip install`、npm 或 API Key。
首次下载计算组件需要网络；运行文件约 14 MB。

在项目根目录依次执行：

```bash
python3 scripts/download_pyodide.py
python3 scripts/stage_browser.py
python3 -m http.server 8000 --directory dist
```

Windows 如果没有 `python3` 命令，可改用 `python`。打开 <http://localhost:8000/>。
不要直接双击 HTML 文件；浏览器 Worker 和文件读取需要通过 HTTP/HTTPS 访问。

第一条命令下载 **Pyodide 0.27.7**，对照 `pyodide-runtime.lock.json` 中的 SHA-256 核验每个文件。
已下载且校验通过的文件会被复用。下载中断后可以重跑；校验不一致时会报错并停止。
第二条命令把网页、Python 核心与计算组件放在 `dist` 中，缺少组件时会提示先下载。

第三条命令只是方便在自己电脑上查看。若希望别人通过公开网址使用，继续第 3 节。

## 3. 部署到 GitHub Pages

仓库自带 `.github/workflows/pages.yml`，通过手动触发完成构建、测试与发布。
普通使用者建议先 Fork 到自己的 GitHub 账号。

1. 在自己的仓库打开 **Settings → Pages**，在 **Build and deployment → Source** 选择 **GitHub Actions**。
2. 如果 Fork 后 Actions 被暂停，在 **Actions** 页面启用自己的工作流。
3. 打开 **Actions → Deploy GitHub Pages → Run workflow**，选择 `main` 并运行。
4. 等待 `build` 和 `deploy` 完成。成功后的 `github-pages` 环境会显示实际网址，**Settings → Pages** 也能看到。
5. 以后更新代码时，再执行一次该工作流。提交代码本身只触发测试，不自动发布 Pages。

该流程会下载经过校验的组件、生成 `dist` 并上传整个目录；不需要配置个人访问令牌。
资源路径支持 `https://账号.github.io/仓库名/` 这种项目子目录，也支持独立域名根目录。

GitHub Free 的 Pages 使用范围是公开仓库；私有仓库是否能启用 Pages 取决于 GitHub 套餐。
以 [GitHub 官方 Pages 说明](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) 为准。

这份工作流与代码复现已在本地验证；不把它的存在等同于已在你的 GitHub 账号开启 Pages。
现有演示网址使用独立托管，上传源码不会把演示网址自动切换成 Pages。

## 4. 部署到其他静态网站平台

也可以上传完整的 `dist` 目录到支持 HTTPS、JavaScript 模块 Worker 和 WebAssembly 的静态托管平台。

- 构建命令依次为 `python3 scripts/download_pyodide.py`、`python3 scripts/stage_browser.py`。
- 发布目录为 `dist`，不是仓库根目录，也不是 `workbench/static`。
- 应正确提供 `.mjs` 的 JavaScript 类型和 `.wasm` 的 `application/wasm` 类型。
- 不需要 Python 服务器进程、数据库、服务端环境变量或 AI 密钥。

`.openai/hosting.json` 属于各自托管项目的身份配置，不随 GitHub 源码分发。
若使用 ChatGPT Sites 搭建副本，应为自己的副本注册托管项目。

## 5. 保留的本地 Python 服务

如果不希望下载浏览器运行组件，可直接运行原来的本地 Python 服务：

```bash
python3 workbench/server.py
```

然后访问 <http://127.0.0.1:8765>。macOS / Windows 也可以使用仓库中的对应启动文件。
该模式共用相同算法，在电脑的 Python 中计算；输出默认位于 `outputs/`。
其可选的远程服务设置保留在 `workbench/server.py`，不影响静态网页版。

## 6. 验证复现结果

完整测试额外需要 Node.js 22，不需要安装 npm 包：

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_ui_rules.cjs tests/test_browser_paths.cjs
python3 scripts/download_pyodide.py
python3 scripts/stage_browser.py
node scripts/test_pyodide.mjs
```

`.github/workflows/test.yml` 在 `main` 提交和拉取请求时运行同一组主要检查。
`test_pyodide.mjs` 使用构建出的同一套 WebAssembly 与 Python 文件，验证计算、导入和 Excel 生成。

简单试用数据：统计同一时段的甲、乙两人，实际工时分别为 40 和 20；本次上限 35；
官方分别下发 35 和 25。结果应为乙向甲转出 **5 小时**，全体差额为 0。
把乙的下发值改为 20 后，总差额为 5 小时，正式转账导出应被拦截，仍允许保存草案并返回修改。

## 7. 常见问题

- **组件下载失败**：确认网络能访问锁定文件中的下载地址后重跑，脚本会复用已校验的文件。
- **页面有界面但不能计算**：检查是否完整发布 `dist`，以及 Worker、Python 文件和 WebAssembly 是否都存在。
- **GitHub Pages 404 或未启用**：检查仓库 Pages 的 Source 是否为 GitHub Actions，并查看工作流中的具体错误。
- **Python 命令找不到**：先安装 Python 3.10+；Windows 可尝试 `python`。
- **刷新后内容丢失**：当前排班和工时草稿在浏览器内存中，离开前下载 Excel。只有主动保存的阶段名单保留在当前浏览器。

## 8. 数据和第三方组件

`outputs/`、`workbench/runtime/`、`.env`、个人托管配置和生成的 `dist/` 已从 GitHub 源码提交范围排除。
`.gitignore` 只按路径排除文件，不能自动判断某个任意文件是否包含真实名单，请只提交虚构示例。

浏览器版的输入在本机处理，不进入共享数据库。公开网站程序不代表公开访问者各自录入的数据。
三条工作流仍由固定代码计算；不引入运行时 AI、金额换算或未经人工确认的业务规则。
第三方运行组件说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
