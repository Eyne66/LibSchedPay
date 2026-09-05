# LibSchedPay

📚 **书库排班与工时配平工作台**

[在线使用](https://libschedpay.bouncy-wren-3789.chatgpt.site) · [下载源码](https://github.com/Eyne66/LibSchedPay/archive/refs/heads/main.zip) · [复现与部署指南](部署与GitHub说明.md) · [业务需求与决策](业务需求与决策记录.md)

这是一个最开始为校园书库学生助理排班和工时整理做的小工具。

我想解决的问题其实很具体：每次确定排班、统计工时、算差值、互相配平，再整理成最后可以交出去的 Excel，都需要在很多名单、数字和表格之间反复操作。人数一多，很容易漏、很容易算错，也很消耗负责人的精力。

所以我把这套工作流慢慢做成了一个可以直接在网页里操作的工作台。

它目前主要做两件事，最后给你三类成品：**排班表、实际工时统计表、工时转账表**。

## 1. 排班

你先确定这一轮的时间范围、岗位、班次、每天需要的人数、工作人员名单，以及每个人明确不能上班的时间。

工作台会根据这些已经确认的信息生成一份尽量均衡的排班草稿，同时统计每个人的岗位和工时。你可以直接在网页里检查和修改，确认之后再导出 Excel。

默认时段是早班 09:00–11:00、下午班 14:00–16:00、晚班 **19:00–22:00**；时间、时长和每天各班的人数都可以改。

它的目的，是先把大量重复的排列、统计和检查工作做掉，再把最后的判断留给人。

## 2. 实际工时整理与工时配平

实际出勤以签到等记录为准，独立于计划排班。

先确定统计时段和本次人员名单，按名单顺序填入、粘贴或上传每个人实际到岗的工时，就能单独导出实际工时统计表。

需要继续配平时，再确认本次个人工时上限，以及官方最终给每个人下发的工时。比如上限是 35h，也可以实际下发 28h；每个人的数值可以分别调整。

工作台会计算每个人“实际工时 − 官方下发工时”的差值，再生成一份人员之间如何互相配平的草稿。

这里处理的单位始终是 **工时**，不涉及工资金额、时薪或者真实银行转账。

如果还没有完全配平，你可以先下载核算草案，退回前面的步骤修改官方下发工时，或者修改配平关系，再重新检查。已经填入的实际工时会保留。只有完全配平后，才能下载正式转账表和公示表。

## 我比较在意的两个使用体验

### 操作尽量简单，工作流尽量明确

我自己本来就不想再为了完成一次排班或工时核算，不停地在 Excel 里复制、粘贴、拉公式、检查名字和数字。

所以现在大部分过程都放到了网页里：

**输入已经确认的数据 → 生成结果 → 网页检查和修改 → 校验 → 下载 Excel。**

希望能让一次排班或工时整理少一些重复的表格办公。

### 最终仍然给你一份真正能继续使用的表格

排班、个人工时汇总、实际工时统计、工时核算草案、正式配平表等都可以导出为 Excel，在浏览器中下载。本地 Python 服务版还支持选择输出文件夹。

像 **学号、银行卡号或者其他更隐私的信息**，没有必要提前交给这个工具。可以先用姓名和工时完成计算，最后再在导出的 Excel 中由负责人自行补充。

这也是我目前比较喜欢的一点：**让程序处理计算和重复劳动，把敏感信息和最后决定尽量留在人手里。**

## 关于这个项目

这个版本首先是根据我自己真正经历过的书库工作流程搭出来的，所以它肯定还带着很强的具体场景痕迹，也很可能还有我没有想到的问题。

如果你也在做类似的工作，发现哪里不好用、哪里逻辑不合理，欢迎 [提 Issue](https://github.com/Eyne66/LibSchedPay/issues) 或告诉我。

至于我能不能改出来……这个我暂时不敢保证 😂

因为我本身并不是软件开发专业出身，这个项目也是我把实际工作流程一点点讲清楚之后，和 AI 一起搭出来、测试、修改到现在的。

也顺便表白一下伟大的 GPT-6（笑）。

但做完以后，我反而觉得这里面的思路可能并不只属于“书库”。比如：

- 学生助理、兼职人员、志愿者等小团队排班；
- 已经确定人员和岗位，只需要在各种时间约束下尽量公平分配工作的场景；
- 某个上级系统先下发一组有限额的数据，但它和实际发生的数据并不完全一致，之后需要在成员之间核对差值、重新配平的场景。

这些问题背后的结构其实很相似：**人负责确认真实规则和特殊情况，程序负责重复计算、检查和整理，最后再回到人手里确认。**

只是受限于我自己的生活经历，我现在能想到和验证的使用场景还很有限。所以目前它首先还是一个：

> **从真实的小型工作流程里长出来的工具。**

如果它刚好也能帮你少做一点重复表格工作，那就很好。

---

下面保留使用、复现和继续开发需要的说明。

## 两种排班口径如何计算

| 选项 | 优先目标 | 班次次数怎么处理 |
| --- | --- | --- |
| 优先总工时均衡 | 尽量缩小所有人总工时的最大差距 | 不要求早、晚班或各时长次数相同 |
| 总工时均衡，并尽量均衡各时长班岗次数 | 同样先追求总工时均衡 | 再尽量平衡各时长次数；早班和下午班同为 2h，合为一组，晚班 3h 为另一组 |

程序先计算总岗次、总工时和人均值，再在整个周期里安排完整班次。不可排要求始终参与计算，不能为了凑平均数而违反。

当前求解会从较小的工时差开始检查整周期的可行安排；搜索完成时显示已验证的最小差距。计算预算用尽时，会明确提示尚未确认最优并保留草稿，不会把这个状态说成“更平均的方案不存在”。

完全相同不一定可行，例如整班时长的组合不合适，或某人只能上 3h 晚班而人均目标是 7h。页面会显示最低、最高工时和最大差距，方便继续判断。

填写**个人目标工时**时，沿用个人目标草稿分配，不启用全员等工时求解。个人目标是参考，不是保证值。手动修改草稿后要重新校验，之前的最优结论也会失效。

这次修复的回归案例是 35 人、245h、部分人员有不可排要求：旧版出现 33 人 7h、1 人 4h、1 人 10h，新版两个模式均得到每人 7h。案例及可行安排保存在测试中，详见 [回归记录](网页版本交付与回归记录.md)。

## 当前能力与边界

| 工作流 | 已确认输入 | 程序处理 | 人工确认 | Excel 输出 |
| --- | --- | --- | --- | --- |
| 排班 | 周期、班次、每日人数、名单、不可排时间、分配口径 | 排班、工时汇总、重复/超员/禁排检查 | 修改安排、重新校验 | 排班表、个人汇总、排班记录、岗位需求 |
| 实际工时统计 | 签到统计时段、名单、每人实际工时 | 姓名、行数与数值校验、汇总 | 核对实际输入 | 实际工时统计表 |
| 工时配平 | 实际工时、逐人下发工时、本次上限 | 算差值、生成配对草稿、核对每人收付 | 修改下发与配平关系 | 核算草案、正式转账表、公示表 |

- 硬约束通过勾选表明确输入。“优先晚班、尽量集中同一天、和某人一起”等软偏好需在草稿中人工调整，当前不自动理解自然语言。
- 转账草案优先同额配对，再匹配剩余差额，尽量少拆分；不保证全局最少笔数。总实际工时与总下发不相等时，内部转账不能消除总量差额。
- 当前网页不内置语音识别；可以用设备自带的语音输入键盘。
- 网页在当前浏览器内运行 Python，不依赖运行时 AI、AI API Key 或共享数据库。姓名核对、算术、硬约束校验和最终配平全部由固定代码处理。
- 当前草稿在刷新、关闭页面后不会保留；离开前请下载所需表格。手动保存的阶段名单存在本浏览器中，尚无跨设备同步。

## 复现同一个网页版

需要 Python 3.10+ 和首次构建时的网络连接；网页使用者不需要安装 Python，也不需要 AI API Key。

```bash
git clone https://github.com/Eyne66/LibSchedPay.git
cd LibSchedPay
python3 scripts/download_pyodide.py
python3 scripts/stage_browser.py
python3 -m http.server 8000 --directory dist
```

然后打开 <http://localhost:8000/>。Windows 可把 `python3` 改为 `python`。
请通过 HTTP 服务访问，不要直接双击 `dist/index.html`。

要获得你自己的公开网址：Fork 仓库，在 **Settings → Pages → Source** 选择 **GitHub Actions**，
再到 **Actions → Deploy GitHub Pages → Run workflow** 执行一次。
部署成功后，网址会显示在该任务的 `github-pages` 环境和仓库 Pages 设置中。
工作流为手动触发，以后更新需要再次运行。详细步骤和故障排查见 [部署指南](部署与GitHub说明.md)。

## 本地 Python 服务（另一种运行方式）

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
- 人工转账：每行 `转出人|转入人|工时`。

上传上一张排班表时，只读取班次、人数、每日人数例外和人员名单作为新周期起点，不会复制旧的具体人员安排。

## 数据与可靠性

- 人员名单按学期或阶段保存，但每个新周期都需要重新确认、增删。
- 每份成品保存当时的名单快照，后续名单变化不会回写历史报表。
- 最终导出前，共用 Python 代码会重新计算并校验；本地模式在服务中运行，静态网页版在浏览器 Worker 中运行。
- 重复导出不会覆盖上一份文件。
- 当前自动测试覆盖 30–40 人名单、每日人数例外、部分目标工时、人工转账配平、草案/正式导出和 Excel 结构。

运行测试（完整验证需要额外安装 Node.js 22；正常使用和构建不需要 Node）：

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_ui_rules.cjs tests/test_browser_paths.cjs
python3 scripts/download_pyodide.py
python3 scripts/stage_browser.py
node scripts/test_pyodide.mjs
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

可以通过 GitHub 的 Code → Download ZIP 下载源码，或 Fork 后独立部署。
当前浏览器版通过 Pyodide 执行原 Python 代码，生成的整个 `dist` 可由 GitHub Pages 等静态托管平台运行。
`workbench/static` 本身不是完整的网页部署包，构建时还要加入 Python 源文件和固定版本运行组件。

仓库只包含程序、虚构示例、文档和测试，不包含实际名单或工时。浏览器版在当前设备处理输入，不设共享数据库。
原 Python HTTP 服务仍保留远程安全模式，部署它与托管静态版是两条不同路线。详见 [部署与GitHub说明.md](部署与GitHub说明.md)。

## English Introduction

LibSchedPay is a local-first utility for campus library student-assistant teams. It provides two independent, auditable workflows:

- generate editable shift-roster drafts from confirmed staffing rules and hard unavailability constraints;
- reconcile actual attendance hours against individually confirmed official issued hours, then export transfer worksheets.

Calculations and XLSX generation are deterministic and do not require an online AI service. Actual attendance is entered separately and is not inferred from the planned schedule. The current transfer workflow operates in work-hour units rather than monetary salary amounts.

## License

No open-source license has been committed yet. If the repository is confirmed for public open-source release, an MIT license can be added deliberately at that time.
