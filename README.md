# LibSchedPay

📚 书库排班与工时转账工作台

> Confirmed input → deterministic calculation → editable review → validated Excel output  
> 输入已确认数据 → 固定脚本计算 → 表格预览修改 → 自动校验 → 输出 Excel 成品

LibSchedPay 是一个面向校园书库学生助理小组的轻量、本地优先工作台，服务于约 10–40 人规模的排班和工时转账整理。

项目只聚焦两个最终交付物：**排班表**与**工时转账表**。数字计算、姓名匹配和 Excel 生成由确定性脚本完成；负责人保留规则确认、特殊情况判断、草稿修改和最终发布权。

## 当前真实能力

排班与转账是两条独立流程。转账依据纸质签到等来源汇总出的**实际到岗工时**，不会直接把计划排班当成实际出勤。

| 模块 | 已确认输入 | 脚本处理 | 人工确认 | Excel 输出 |
| --- | --- | --- | --- | --- |
| 排班 | 周期、班次、每日人数、当前人员、不可排时间、分配口径 | 生成均衡草稿、统计岗位与工时、检查重复/超员/禁排 | 调整姓名和特殊安排 | 排班表、排班记录、个人工时汇总 |
| 工时转账 | 统计时段、当前人员、实际工时、逐人官方下发工时、上限 | 计算实际/下发差值、生成转账配对草案、核对收付 | 调整下发工时和人工转账关系 | 实际工时一览、核算草案、正式转账表、公示表 |

### 排班工作流

1. 确认排班开始日期和结束日期。
2. 录入班次时间、时长、默认人数；必要时设置某一天的特殊人数。
3. 录入或上传本周期人员名单。
4. 在“人员 × 日期 × 班次”表格中勾选绝对不能排的时间。
5. 选择按总工时平均，或按 2 小时班、3 小时班等班岗时长分别平衡；个人目标工时可选填。
6. 生成可编辑草稿，重新校验后输出 Excel。

### 工时转账工作流

1. 确认本次统计的具体开始日期、结束日期和官方下发工时上限。
2. 录入或上传本次人员名单。
3. 按姓名顺序粘贴、逐格填写或上传每个人的实际到岗工时。
4. 逐人确认官方下发工时；系统不会强制所有人使用同一个数字。
5. 计算实际工时与官方下发工时的差值，生成尽量少拆分的转账配对草案。
6. 人工修改并校验“付款人|收款人|工时”；未配平时可输出核算草案，完全配平后输出正式表和公示表。

## 能力边界

- 当前排班器可靠处理的是明确的**硬约束**，例如某人某天某班绝对不能排。
- “优先晚班、尽量在同一天、尽量和某人一起”等软偏好目前不会被自然语言自动执行，需要在草稿中人工调整。
- 实际出勤仍以签到统计为准；计划排班不会自动变成工资依据，也不记录每一次代班关系。
- 转账表使用的是**工时单位**，当前不计算时薪、人民币金额、税费或银行付款。
- 项目不内置语音识别，也不依赖在线 AI 服务；可以使用电脑或手机自带的语音输入键盘录入文字。
- 运行时 AI 不是计算正确性的前提。姓名、工时、配平和 Excel 均由本地固定脚本处理。

## Quick Start

要求：Python 3.10 或更高版本；不需要安装第三方 Python 包、Node、npm 或 openpyxl。

### macOS

双击：

```text
启动书库工作台.command
```

### Windows

双击：

```text
启动书库工作台.bat
```

### Linux 或命令行

```bash
python3 workbench/server.py
```

然后打开：<http://127.0.0.1:8765>

默认输出保存在 `outputs/`。本地运行时也可以在输出按钮旁选择其他文件夹；生成后同时提供浏览器“下载 Excel”。

## 支持的输入方式

- 人员名单：逐行粘贴姓名，或上传 `.xlsx`、`.csv`、`.json`。
- 实际工时：逐格填写；按名单顺序一行一个数字；使用“姓名 工时”；或上传姓名/实际工时表。
- 排班结构：手工填写班次，或上传上一张成品排班表作为结构参考。
- 硬约束：网页勾选表；高级入口兼容 `姓名|YYYY-MM-DD|班次编号`。
- 人工转账：每行 `付款人|收款人|工时`。

上传上一张排班表时，只读取班次、人数、每日人数例外和人员名单作为新周期起点，不会复制旧的具体人员安排。

## 数据与可靠性

- 人员名单按学期或阶段保存，但每个新周期都需要重新确认、增删。
- 每份成品保存当时的名单快照，后续名单变化不会回写历史报表。
- 最终导出前，后端会重新计算并校验，不信任网页中可能过期的结果。
- 重复导出不会覆盖上一份文件。
- 当前自动测试覆盖 30–40 人名单、每日人数例外、部分目标工时、人工转账配平、草案/正式导出和 Excel 结构。

运行测试：

```bash
python3 -m unittest discover -s tests -v
node --check workbench/static/app.js
```

## 项目结构

```text
workbench/                  本地网页和 Python 服务
src/book_workbench/         排班、工时转账、Excel 核心
tests/                      自动回归测试
scripts/                    命令行与 Excel 校验脚本
examples/                   不含真实人员信息的示例输入
部署与GitHub说明.md          GitHub 与在线部署边界
工程交接说明.md              后续继续开发的业务与工程说明
业务需求与决策记录.md      为什么这样设计、需求变更和新 Agent 续接指令
```

## 分发与部署

可以发送完整压缩包给其他有 Python 的电脑本地运行，也可以把代码放入 GitHub 仓库。GitHub Pages 不能运行当前 Python 计算和 Excel 服务；在线版本需要支持 Python 的部署平台。

人员姓名、课表和工时不应提交到公开仓库。在线运行时可启用账号密码和“远程安全模式”；面向多用户的长期公开部署仍需要规划账号权限、数据保留期限和备份。详见 [部署与GitHub说明.md](部署与GitHub说明.md)。

## English Introduction

LibSchedPay is a local-first utility for campus library student-assistant teams. It provides two independent, auditable workflows:

- generate editable shift-roster drafts from confirmed staffing rules and hard unavailability constraints;
- reconcile actual attendance hours against individually confirmed official issued hours, then export transfer worksheets.

Calculations and XLSX generation are deterministic and do not require an online AI service. Actual attendance is entered separately and is not inferred from the planned schedule. The current transfer workflow operates in work-hour units rather than monetary salary amounts.

## License

No open-source license has been committed yet. If the repository is confirmed for public open-source release, an MIT license can be added deliberately at that time.
