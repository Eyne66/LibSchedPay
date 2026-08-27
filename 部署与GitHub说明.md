# LibSchedPay 部署与 GitHub 说明

## 建议的 GitHub 信息

- 仓库名：`LibSchedPay`
- GitHub About 短描述：`Local-first tool for library student-assistant scheduling, work-hour reconciliation, and transfer-sheet generation.`

这句描述与当前构建一致：项目处理的是排班、实际/下发工时核对和工时转账表，不宣称已经计算人民币工资，也不宣称排班结果会自动成为实际出勤。

## 当前可以怎样使用

当前版本是“浏览器界面 + Python 本地服务”。它不依赖第三方 Python 包，适合放进 GitHub 仓库、制作 GitHub Release 压缩包，或在有 Python 的电脑上本地运行。

本地启动：

```bash
python3 workbench/server.py
```

默认只监听 `127.0.0.1:8765`，同一网络中的其他人不能直接访问，人员姓名和工时也不会自动上传到互联网。

## 上传到 GitHub 仓库

可以把整个项目上传到 GitHub，但不要上传实际人员名单、实际工资数据、`outputs/` 成品或 `workbench/runtime/` 临时文件。项目中的 `.gitignore` 已经默认排除这些内容。

仓库上传后，`.github/workflows/test.yml` 会在每次提交和拉取请求时自动运行：

- Python 3.10、3.11、3.12、3.13 兼容性检查；
- 网页 JavaScript 语法检查；
- 排班、转账、Excel 导出的完整回归测试。

建议把可转发压缩包放在 GitHub Releases 中，不要把压缩包本身反复提交进代码历史。

## GitHub Pages 的限制

GitHub Pages 只能托管静态网页，不能运行本项目的 Python 计算、Excel 导入和 Excel 生成服务。因此当前版本不能只把 `workbench/static/` 放进 GitHub Pages 就正常工作。

如果以后希望获得一个任何设备都能打开的网址，有两条路线：

1. 保留当前 Python 计算核心，部署到支持 Python 的服务；浏览器通过“下载 Excel”保存成品。
2. 把计算和 Excel 生成全部改写成浏览器端 JavaScript，再使用 GitHub Pages。这个改动较大，且需要重新做一轮计算一致性测试。

当前更适合第一条路线。

## 在支持 Python 的平台运行

服务支持常见部署平台提供的 `PORT` 环境变量，也可以手动设置监听地址：

```bash
BOOK_WORKBENCH_HOST=0.0.0.0 PORT=8000 python3 workbench/server.py
```

在线运行时，网页生成成品后使用“下载 Excel”。“选择输出位置”和“在 Finder 中显示”属于本机功能，不适用于远程服务器。

在线版建议使用远程安全模式和访问密码：

```bash
BOOK_WORKBENCH_REMOTE=1 \
BOOK_WORKBENCH_HOST=0.0.0.0 \
PORT=8000 \
BOOK_WORKBENCH_USERNAME=your-user \
BOOK_WORKBENCH_PASSWORD=your-strong-password \
python3 workbench/server.py
```

`BOOK_WORKBENCH_REMOTE=1` 会忽略浏览器传入的本机保存路径，禁用选择文件夹和打开服务器文件管理器的接口；用户通过 HTTPS 网页直接下载 Excel。账号与密码两项都设置后，所有页面、计算、上传和下载接口都要先通过验证。

## 公开部署前必须补的安全项


当前在线模式提供一组 HTTP Basic 访问账号，适合负责人本人或小范围测试，不是多用户权限系统。人员姓名、课表和工时属于不适合公开暴露的数据。因此在把网址长期公开给多人使用之前，仍需要增加分账号权限、数据保留期限、自动清理和备份规则。

用于临时测试时，应使用 HTTPS、强密码和难以猜测的网址，不要将账号密码公开发布。代码可以放到私有 GitHub 仓库，但不要把现实人员数据和成品表格提交进仓库。
