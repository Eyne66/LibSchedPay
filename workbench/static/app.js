const $ = id => document.getElementById(id);

const state = {
  mode: null,
  step: null,
  remoteMode: typeof window !== "undefined" && !!window.workbenchBackend,
  outputDir: localStorage.getItem("bookWorkbench.outputDir") || "",
  schedule: {start: "", end: "", shifts: [], people: [], constraints: [], day_requirements: {}, targets: {}, allocation_mode: "total_hours", result: null},
  settlement: {start: "", end: "", cap: 40, people: [], rows: [], result: null},
};
const STEPS = {schedule: ["period", "shifts", "people", "constraints", "plan", "draft"], settlement: ["period", "people", "actual", "issued", "transfer"]};
const DEFAULT_SHIFT_IDS = "morning=早班；afternoon=下午班；evening=晚班";

function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", "\"":"&quot;"}[c])); }
function lineParts(text) { return String(text || "").split(/\n/).map(x => x.trim()).filter(Boolean); }
function uniqueNames(text) { return lineParts(text).flatMap(x => x.split(/[，,、]/)).map(x => x.trim()).filter(Boolean); }
function setStatus(text, error = false) { $("status").textContent = text; $("status").style.color = error ? "var(--red)" : "var(--green)"; }
function outputLocationLabel() { return state.remoteMode ? "下载到当前设备" : (state.outputDir || "项目 outputs 文件夹"); }
function renderOutputLocation() { document.querySelectorAll("[data-output-dir-label]").forEach(node => { node.textContent = outputLocationLabel(); }); }
function outputPickerMarkup() { if (state.remoteMode) return `<span class="output-picker-label">输出方式：<strong data-output-dir-label>${escapeHtml(outputLocationLabel())}</strong></span>`; return `<span class="output-picker-label">保存到：<strong data-output-dir-label>${escapeHtml(outputLocationLabel())}</strong></span><button class="output-picker-button" data-action="choose-output-dir">选择输出位置</button>`; }
function showOutput(path, label, downloadUrl = "") { const result = $("outputResult"); result.classList.remove("hidden"); const download = downloadUrl ? `<a class="primary-button" href="${escapeHtml(downloadUrl)}" download="${escapeHtml(path.split("/").pop())}">下载 Excel</a>` : ""; const location = state.remoteMode ? "" : `<span class="output-path">${escapeHtml(path)}</span>`; const reveal = state.remoteMode ? "" : `<button class="secondary-button" id="revealOutput">在Finder中显示</button>`; result.innerHTML = `<p><strong>${escapeHtml(label)}已生成</strong></p>${location}<div class="actions">${download}${reveal}</div>`; $("revealOutput")?.addEventListener("click", async () => { try { await api("/api/reveal-output", {path}); } catch (e) { alert(e.message); } }); result.scrollIntoView({behavior: "smooth", block: "nearest"}); }
function addMessage(kind, text) { const box = document.createElement("div"); box.className = `message ${kind}`; box.innerHTML = `<span class="message-tag">${kind === "user" ? "你" : "工作台"}</span><p>${escapeHtml(text)}</p>`; $("chatLog").appendChild(box); $("chatLog").scrollTop = $("chatLog").scrollHeight; }
function api(path, payload) { if (typeof window !== "undefined" && window.workbenchBackend) return window.workbenchBackend.request(path, payload); return fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)}).then(async response => { const data = await response.json(); if (!response.ok || data.ok === false) throw new Error(data.error || "请求失败"); return data; }); }
function datesBetween(start, end) { const out = []; let d = new Date(`${start}T00:00:00`), last = new Date(`${end}T00:00:00`); const format = value => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`; while (d <= last) { out.push(format(d)); d.setDate(d.getDate() + 1); } return out; }
function timeText(value) { const raw = String(value || "").trim(); if (!raw) return ""; if (raw.includes(":")) return raw; const n = Number(raw); return Number.isFinite(n) ? `${String(n).padStart(2, "0")}:00` : raw; }
function duration(start, end) { const parse = value => { const parts = value.split(":").map(Number); return parts[0] * 60 + (parts[1] || 0); }; return (parse(end) - parse(start)) / 60; }
function metric(label, value) { return `<div class="summary-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`; }
function formatNumber(value) { const number = Number(value); return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, ""); }
function weekdayLabel(date) { return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][new Date(`${date}T00:00:00`).getDay()]; }
function requiredPeopleForDate(s, date, shift) { return Number(s.day_requirements?.[date]?.[shift.id] ?? shift.required_people); }
function allocationBreakdownText(s) { const dates = datesBetween(s.start, s.end); const peopleCount = s.people.length || 0; const groups = {}; dates.forEach(date => s.shifts.forEach(shift => { const durationHours = Number(shift.duration_hours); const key = String(durationHours); if (!groups[key]) groups[key] = {duration: durationHours, slots: 0, total: 0}; const required = requiredPeopleForDate(s, date, shift); groups[key].slots += required; groups[key].total += durationHours * required; })); return Object.values(groups).sort((a, b) => a.duration - b.duration).map(group => `${formatNumber(group.duration)}小时班：${formatNumber(group.total)}小时总量，${group.slots}个班次${peopleCount ? `，按${peopleCount}人平均约${formatNumber(group.total / peopleCount)}小时/人` : ""}`).join("；"); }
function plannedHoursForSchedule(s) { return datesBetween(s.start, s.end).reduce((total, date) => total + s.shifts.reduce((dayTotal, shift) => dayTotal + Number(shift.duration_hours) * requiredPeopleForDate(s, date, shift), 0), 0); }
function constraintGridMarkup(s) { const dates = datesBetween(s.start, s.end); const checked = new Set(s.constraints.map(item => `${nameKey(item.name)}|${item.date}|${item.shift_id}`)); const rows = s.people.flatMap(person => dates.map(date => `<tr><th>${escapeHtml(person.name)}</th><td>${weekdayLabel(date)}<br><small>${date}</small></td>${s.shifts.map(shift => { const key = `${nameKey(person.name)}|${date}|${shift.id}`; return `<td class="constraint-check-cell"><label title="勾选表示${escapeHtml(person.name)}在${date}不能上${escapeHtml(shift.name)}"><input class="constraint-check" type="checkbox" data-name="${escapeHtml(person.name)}" data-date="${date}" data-shift="${escapeHtml(shift.id)}" ${checked.has(key) ? "checked" : ""}><span>${escapeHtml(shift.name)}</span></label></td>`; }).join("")}</tr>`)).join(""); const headers = s.shifts.map(shift => `<th>${escapeHtml(shift.name)}<br><small>${escapeHtml(shift.start || "")}–${escapeHtml(shift.end || "")}</small></th>`).join(""); return `<div class="constraint-grid-help">下面只需要勾选“绝对不能排”的格子。空白就是可以排；“优先、尽量、希望、自由安排”不用填。系统会把勾选结果自动转换成内部约束。</div><div class="data-wrap constraint-grid-wrap"><table class="data-table constraint-grid"><thead><tr><th>人员</th><th>日期</th>${headers}</tr></thead><tbody>${rows}</tbody></table></div>`; }
function readConstraintGrid() { return [...document.querySelectorAll(".constraint-check:checked")].map(input => ({name: input.dataset.name, date: input.dataset.date, shift_id: input.dataset.shift})); }

function modeLabel() { return state.mode === "schedule" ? "排班表" : "工时统计与转账"; }
function constraintPrompt() {
  const s = state.schedule;
  const period = s.start && s.end ? `${s.start} 至 ${s.end}` : "（请填写排班开始日期和结束日期）";
  const shifts = s.shifts.length ? s.shifts.map(shift => `${shift.id}=${shift.name}（${shift.start}-${shift.end}，${shift.required_people}人）`).join("；") : DEFAULT_SHIFT_IDS;
  return `你是“排班约束整理器”，不是排班决策器。请把我提供的自然语言排班要求，整理成书库工作台可以识别的格式。\n\n排班周期：${period}\n班次编号：${shifts}\n\n请严格按以下规则处理：\n1. 只提取明确的硬约束，例如“不能排”“只能排”“仅限某几天”“不允许跨天”。\n2. 每条硬约束单独一行，严格输出为：姓名|YYYY-MM-DD|班次编号\n3. 把“周一、周二”等星期，按照排班周期换算成具体日期。\n4. “自由安排”“优先”“尽量”“希望”“可以少排”等，不要转换成硬约束，放到“软偏好或待确认”部分。\n5. 不要添加原文没有明确说过的人名、日期或班次。\n6. 如果一句话有歧义、冲突，或无法确定具体班次，请放到“待确认”，不要猜测。\n7. 第一部分只能放可以直接粘贴到工作台的硬约束行；不要加编号、解释、表头或代码围栏。\n\n请按以下格式输出：\n【可直接粘贴到工作台的硬约束】\n姓名|YYYY-MM-DD|班次编号\n\n【软偏好或待确认】\n逐条列出，供我人工判断；这一部分不要粘贴到工作台。\n\n原始排班要求：\n（把我的排班要求粘贴在这里）`;
}
async function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  const helper = document.createElement("textarea"); helper.value = text; helper.setAttribute("readonly", ""); helper.style.position = "fixed"; helper.style.opacity = "0"; document.body.appendChild(helper); helper.select(); const copied = document.execCommand("copy"); helper.remove(); if (!copied) throw new Error("复制失败，请手动选中提示词复制");
}
function setMode(mode, fromChat = false) {
  state.mode = mode; state.step = "period"; $("outputResult").classList.add("hidden"); $("workCard").classList.remove("hidden");
  document.querySelectorAll(".mode-choice").forEach(button => button.classList.toggle("active", button.dataset.mode === mode));
  $("workEyebrow").textContent = mode === "schedule" ? "01 / SCHEDULE" : "02 / SETTLEMENT"; $("workTitle").textContent = modeLabel();
  $("workDescription").textContent = mode === "schedule" ? "先确认班次和人员，再生成可以修改的排班草稿。" : "先确认统计时段和人员，再逐人录入实际工时、下发工时和转账。";
  if (!fromChat) addMessage("assistant", `好的，现在做${modeLabel()}。我们一步一步来，先确认${mode === "schedule" ? "排班周期" : "本次统计时段"}。`);
  setStatus(`正在制作${modeLabel()}`); renderStep(); $("workCard").scrollIntoView({behavior: "smooth", block: "start"});
}
function restart() { state.mode = null; state.step = null; state.schedule = {start: "", end: "", shifts: [], people: [], constraints: [], day_requirements: {}, targets: {}, allocation_mode: "total_hours", result: null}; state.settlement = {start: "", end: "", cap: 40, people: [], rows: [], result: null}; $("workCard").classList.add("hidden"); $("outputResult").classList.add("hidden"); document.querySelectorAll(".mode-choice").forEach(button => button.classList.remove("active")); addMessage("assistant", "已清空当前工作。你可以重新选择排班表或转账表。"); setStatus("等待开始"); }
function progress() { const steps = STEPS[state.mode] || [], current = steps.indexOf(state.step); $("progressLine").innerHTML = steps.map((_, i) => `<span class="progress-dot ${i < current ? "done" : i === current ? "current" : ""}"></span>`).join(""); }
function nextStep(step) { $("outputResult").classList.add("hidden"); state.step = step; renderStep(); $("workCard").scrollIntoView({behavior: "smooth", block: "start"}); }

function renderStep() {
  if (!state.mode) return; progress(); let title, help, kicker;
  if (state.mode === "schedule") { const c = {period: ["第1步 / 6", "先确认排班周期", "只需要告诉我这一周从哪天到哪天。"], shifts: ["第2步 / 6", "确认班次和每班人数", "把老师确认的班次填进来。可以直接使用自然写法，不要求记编号。"], people: ["第3步 / 6", "收集本周期人员", "可以粘贴姓名，也可以上传问卷收集表。系统只把当前确认参加的人放进本周期。"], constraints: ["第4步 / 6", "处理硬约束", "这里只记录明确的“绝对不能排”。偏好可以留到排班草稿里人工调整；没有硬约束可以直接跳过。"], plan: ["第5步 / 6", "确认总工时分配方式", "默认按计划总工时平均估算。你如果已经决定谁大约排几小时，可以在这里补充；填写个人目标后，将按你的目标安排，不再以所有人工时相同为目标。"], draft: ["第6步 / 6", "检查排班草稿", "草稿可以直接编辑。确认没有重复、不可排和人数异常后，才能输出成品。"]}; [kicker, title, help] = c[state.step]; }
  else { const c = {period: ["第1步 / 5", "先确认工时统计时段", "填写本次实际签到工时的统计范围，后续表格会使用这个日期表头。"], people: ["第2步 / 5", "录入或上传本次人员名单", "先确定这次结算有哪些人，再逐人录入实际到岗工时。人员每个阶段都可以重新确认。"], actual: ["第3步 / 5", "逐一录入并校对实际工时", "每个人的实际工时都可以修改；填错了直接改表格。确认后可以单独输出一览表和合计工时。"], issued: ["第4步 / 5", "逐人确认官方下发工时", "先确认本次上限，再填写每个人的下发工时。可以反复返回调整，实际工时会保留。"], transfer: ["第5步 / 5", "配平并输出转账表", "系统根据你确认的下发工时计算差值，先生成尽量少的转账配对；你可以修改并校验后输出。"]}; [kicker, title, help] = c[state.step]; }
  $("stepKicker").textContent = kicker; $("stepTitle").textContent = title; $("stepHelp").textContent = help; $("stepContent").innerHTML = state.mode === "schedule" ? renderScheduleStep() : renderSettlementStep(); bindStepEvents(); renderSummary(); renderOutputLocation();
}

function renderScheduleStep() {
  const s = state.schedule;
  if (state.step === "period") return `<div class="form-row"><label class="field">开始日期<input id="scheduleStart" type="date" value="${escapeHtml(s.start)}"></label><label class="field">结束日期<input id="scheduleEnd" type="date" value="${escapeHtml(s.end)}"></label></div><div class="actions"><button class="primary-button" id="confirmSchedulePeriod">确认周期，下一步</button></div>`;
  if (state.step === "shifts") return renderShiftEditor(s);
  if (state.step === "people") return `<label class="field full">本周期人员名单<textarea id="peopleInput" class="large-area" placeholder="每行一个姓名">${escapeHtml(s.people.map(p => p.name).join("\n"))}</textarea></label><div class="roster-row"><input id="stageName" placeholder="阶段名单名称（可选，例如：2026暑期学校）"><select id="rosterSelect"><option value="">载入已保存的阶段名单</option></select><button class="secondary-button" id="saveRoster">保存名单</button><button class="ghost-button" id="loadRoster">载入名单</button></div><div class="actions"><input id="questionnaireFile" class="file-input" type="file" accept=".xlsx,.csv,.json"><button class="secondary-button" id="importQuestionnaire">读取问卷表</button><button class="primary-button" id="confirmPeople">确认人员，下一步</button><button class="ghost-button" id="backStep">返回上一步</button></div><p class="inline-note">当前名单：<strong id="peopleCount">0</strong> 人。30–40人是正常规模，本周期人数可以随机增删，系统按实际名单扩展。</p>`;
  if (state.step === "constraints") return `<div class="constraint-entry-head"><strong>逐格标记绝对不能排的时间</strong><span>不需要手写姓名、日期或班次编号。每一行是一个人某一天，勾选对应班次即可。</span></div>${constraintGridMarkup(s)}<details class="prompt-panel"><summary>高级入口：粘贴其他 AI 整理好的硬约束</summary><div class="prompt-panel-body"><p class="inline-note">格式仍为每行：姓名|YYYY-MM-DD|班次编号。粘贴后点击确认，系统会和上面的勾选结果合并。</p><textarea id="constraintInput" class="large-area" placeholder="例如：同学甲|2026-08-25|afternoon">${escapeHtml(s.constraints.map(x => `${x.name}|${x.date}|${x.shift_id}`).join("\n"))}</textarea><div class="constraint-format-note"><strong>可识别班次编号</strong><span>morning=早班，afternoon=下午班，evening=晚班</span><span>只有“不能排、只能排”才进入这里；优先、尽量、希望、自由安排不要当成硬约束。</span></div><div class="prompt-panel-body"><p class="inline-note">需要先让其他 AI 整理时，可以复制下面的提示词；输出的硬约束再粘贴回上面的高级入口。</p><textarea id="constraintPrompt" class="prompt-area" readonly>${escapeHtml(constraintPrompt())}</textarea><button class="secondary-button" id="copyConstraintPrompt" type="button">复制整理提示词</button></div></details><p class="inline-note">没有硬约束时，保持全部空白，直接点击“没有硬约束，下一步”。</p><div class="actions"><button class="primary-button" id="confirmConstraints">确认约束，下一步</button><button class="secondary-button" id="skipConstraints">没有硬约束，下一步</button><button class="ghost-button" id="backStep">返回上一步</button></div>`;
  if (state.step === "plan") return `<label class="field full">预估分配口径<select id="allocationMode"><option value="total_hours" ${s.allocation_mode === "by_duration" ? "" : "selected"}>优先总工时均衡（不要求班次次数相同）</option><option value="by_duration" ${s.allocation_mode === "by_duration" ? "selected" : ""}>总工时均衡，并尽量均衡各时长班岗次数</option></select></label><label class="field full">每个人目标工时（可选）<textarea id="targetInput" class="large-area" placeholder="每行一人，例如：\n同学甲|8\n同学乙 8小时\n同学丙：9工时">${escapeHtml(Object.entries(s.targets).map(([name, hours]) => `${name}|${hours}`).join("\n"))}</textarea></label><div class="constraint-format-note"><strong>可识别写法</strong><span>姓名|数字　例如：同学甲|8</span><span>姓名 数字小时　例如：同学乙 8小时</span><span>姓名：数字工时　例如：同学丙：9工时</span><span>不填写个人目标时，系统按上面的分配口径自动估算；填写后会作为人工目标参考，之后仍可在草稿中修改。</span></div><p class="inline-note">计划总工时：<strong id="plannedHoursHint">计算中</strong> h。名单 <strong>${s.people.length}</strong> 人，平均约 <strong>${formatNumber(plannedHoursForSchedule(s) / Math.max(s.people.length, 1))}</strong> h / 人。各时长班岗统计：<span id="allocationBreakdown">${escapeHtml(allocationBreakdownText(s))}</span>。两种方式都会先求总工时尽量接近；第二种再尽量均衡 2 小时岗、3 小时岗各自的次数。早班和下午班同为 2 小时，因此归为一组。完整班次不能拆开。</p><div class="actions"><button class="primary-button" id="confirmPlan">生成排班草稿</button><button class="ghost-button" id="backStep">返回上一步</button></div>`;
  return renderScheduleDraft();
}
function renderScheduleDraft() {
  const result = state.schedule.result; if (!result) return `<div class="empty-box">还没有排班草稿。</div>`; const v = result.validation, t = v.totals;
  const rows = v.shift_results.map((r, i) => `<tr><td>${escapeHtml(r.date)}</td><td>${escapeHtml(r.shift_name)}<br><small>${escapeHtml(r.shift_id)}</small></td><td><input class="schedule-assignment" data-index="${i}" value="${escapeHtml(r.assigned_people.join("，"))}"></td><td>${r.required_people}</td><td class="${r.vacancy_count ? "warning-text" : "ok"}">${r.vacancy_count}</td><td>${r.duplicates.length ? `<span class="error-text">重复：${r.duplicates.map(escapeHtml).join("、")}</span>` : ""}${r.unavailable_people.length ? `<span class="error-text">不可排：${r.unavailable_people.map(escapeHtml).join("、")}</span>` : ""}</td></tr>`).join("");
  const notice = v.errors.length ? `<div class="inline-note warning">${v.errors.map(escapeHtml).join("；")}</div>` : v.warnings.length ? `<div class="inline-note warning">${v.warnings.map(escapeHtml).join("；")}</div>` : `<div class="inline-note">当前草稿基础校验通过。仍建议你按实际情况看一遍人员安排。</div>`;
  return `<div class="summary-grid">${metric("计划岗位", t.planned_slots)}${metric("已排岗位", t.filled_slots)}${metric("空缺", t.vacancy_slots)}${metric("计划工时", t.planned_hours)}${metric("平均目标 / 人", formatNumber(Number(t.planned_hours) / Math.max(v.people.length, 1)))}${metric("已排工时", t.filled_hours)}</div>${notice}${balanceNoticeMarkup(result)}${personalHoursMarkup(v)}<div class="data-wrap" style="margin-top:15px"><table class="data-table"><thead><tr><th>日期</th><th>班次</th><th>人员（可编辑）</th><th>需要人数</th><th>空缺</th><th>异常</th></tr></thead><tbody>${rows}</tbody></table></div><div class="actions"><button class="secondary-button" id="validateSchedule">重新校验</button><button class="primary-button" id="exportSchedule" ${v.ok ? "" : "disabled"}>确认并输出排班 Excel</button><div class="output-picker-inline">${outputPickerMarkup()}</div><button class="ghost-button" id="backStep">返回修改前置数据</button></div>`;
}

function renderSettlementStep() {
  const s = state.settlement;
  if (state.step === "period") return `<div class="form-row"><label class="field">统计开始日期<input id="settlementStart" type="date" value="${escapeHtml(s.start)}"></label><label class="field">统计结束日期<input id="settlementEnd" type="date" value="${escapeHtml(s.end)}"></label></div><p class="inline-note">按你已经汇总的签到工时统计。实际工时表可以单独下载；需要转账配平时，再确认本次下发上限。</p><div class="actions"><button class="primary-button" id="confirmSettlementPeriod">确认时段，下一步</button></div>`;
  if (state.step === "people") return `<label class="field full">本次结算人员名单<textarea id="settlementPeopleInput" class="large-area" placeholder="每行一个姓名">${escapeHtml(s.people.join("\n"))}</textarea></label><div class="actions"><input id="rosterFile" class="file-input" type="file" accept=".xlsx,.csv,.json"><button class="secondary-button" id="importSettlementRoster">读取人员名单</button><button class="primary-button" id="confirmSettlementPeople">确认人员，下一步</button><button class="ghost-button" id="backStep">返回上一步</button></div><p class="inline-note">当前名单：<strong id="settlementPeopleCount">${s.people.length}</strong> 人。可以是随机30–40人，不要求和上一次名单相同。</p>`;
  if (state.step === "actual") {
    if (!s.rows.length) s.rows = s.people.map(name => ({name, actual_hours: null, issued_hours: null}));
    const rows = s.rows.map((row, i) => `<tr><td>${i + 1}</td><td>${escapeHtml(row.name)}</td><td><input class="actual-hour-input" data-index="${i}" type="number" min="0" step="any" value="${row.actual_hours ?? ""}" placeholder="填写工时"></td></tr>`).join("");
    const bulkValue = s.rows.map(row => row.actual_hours ?? "").join("\n");
    return `<label class="field full">批量录入（推荐：按姓名顺序，一行一个工时）<textarea id="actualBulkInput" class="short-area" placeholder="第1行对应第1个姓名\n82\n74\n29\n……">${escapeHtml(bulkValue)}</textarea></label><p class="inline-note">当前名单共 <strong>${s.rows.length}</strong> 人。按名单顺序粘贴工时即可：第1行对应第1个姓名，第2行对应第2个姓名。也支持每行写“姓名 工时”。<span id="actualInputHint"></span></p><div class="actions"><button class="secondary-button" id="applyBulkActual">按名单顺序整理到表格</button><input id="attendanceFile" class="file-input" type="file" accept=".xlsx,.csv,.json"><button class="secondary-button" id="importAttendance">读取实际工时表</button></div><div class="data-wrap" style="margin-top:15px"><table class="data-table"><thead><tr><th>序号</th><th>姓名</th><th>实际工时（可修改）</th></tr></thead><tbody>${rows}</tbody></table></div><div class="actions"><button class="secondary-button" id="exportSummary">输出实际工时统计表</button><div class="output-picker-inline">${outputPickerMarkup()}</div><button class="primary-button" id="confirmActual">确认实际工时，下一步</button><button class="ghost-button" id="backStep">返回上一步</button></div><p class="inline-note">确认前可以反复修改；输出的一览表包含每个人和实际工时合计。</p>`;
  }
  if (state.step === "issued") { const rows = s.rows.map((r, i) => `<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.actual_hours)}</td><td><input class="issued-input" data-index="${i}" type="number" min="0" step="any" value="${r.issued_hours ?? ""}"></td></tr>`).join(""); return `<label class="field">本次官方下发上限（小时）<input id="issuedCap" type="number" min="0" step="any" value="${escapeHtml(s.cap)}"></label><p class="inline-note">请确认本次上限，例如 30、35 或 40。每个人可分别填写，不必全部发到上限。</p><div class="data-wrap" style="margin-top:15px"><table class="data-table"><thead><tr><th>姓名</th><th>实际工时</th><th>官方下发工时（可编辑）</th></tr></thead><tbody>${rows}</tbody></table></div><div class="actions"><button class="secondary-button" id="fillIssued33">全部填入${s.cap}</button><button class="secondary-button" id="fillIssuedActual">按实际填入（不超过上限）</button><button class="primary-button" id="calculateSettlement">计算差值，下一步</button><button class="ghost-button" id="backStep">返回上一步</button></div><p class="inline-note">这是确认动作：如果某人官方下发28小时，就填28；只有点击批量填入，才会按你的选择填写。</p>`; }
  return renderSettlementTransfer();
}
function renderSettlementTransfer() {
  const result = state.settlement.result; if (!result) return `<div class="empty-box">还没有差值结果。</div>`; const t = result.totals;
  const rows = result.people.map(r => `<tr><td>${escapeHtml(r.name)}</td><td>${r.actual_hours}</td><td>${r.issued_hours}</td><td class="${Number(r.difference_hours) > 0 ? "ok" : Number(r.difference_hours) < 0 ? "warning-text" : ""}">${r.difference_hours}</td><td>${r.status}</td></tr>`).join("");
  const transferCheck = result.transfer_validation;
  const transferNotice = transferCheck ? (transferCheck.ok ? `<p class="inline-note">人工转账配平校验通过，可以输出最终转账表和公示表。</p>` : `<p class="inline-note warning">当前还不能输出最终转账表：${friendlyTransferErrors(transferCheck.errors).map(escapeHtml).join("；")}。你可以继续修改，或先输出“当前核算草案”保存差值明细。</p>`) : "";
  const balanceNotice = result.checks.net_difference_is_zero ? "当前总差额为0，配平后可以输出最终转账表。" : `当前存在外部差额 ${escapeHtml(t.external_adjustment_hours)} 小时：最终转账必须先调整官方下发工时使总差额为0；但仍可以先输出当前核算草案。`;
  return `<div class="summary-grid">${metric("实际总工时", t.actual_hours)}${metric("下发总工时", t.issued_hours)}${metric("总差额", t.difference_hours)}${metric("应收", t.receivable_hours)}${metric("应转出", t.payable_hours)}${metric("未配平", t.external_adjustment_hours)}${metric("转账笔数", result.transfers.length)}</div><div class="data-wrap" style="margin-top:15px"><table class="data-table"><thead><tr><th>姓名</th><th>实际</th><th>下发</th><th>差值</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></div><div class="inline-note">这里进入人工配平：正差值是应收，负差值是应转出。录入文本固定使用“转出人|转入人|工时”，也就是前面的人把这部分工时差额转给后面的人；但公示表会把转入人放在第一列显示正数，把转出人放在第二列显示负数。草案优先同额配对，再匹配剩余差额，尽量减少拆分；不保证笔数是全局最少。你可以逐行修改，也可以返回调整下发数再试一次。</div><label class="field full" style="margin-top:15px">人工转账配平表（可编辑，每行：转出人|转入人|工时）<textarea id="transferInput" class="large-area">${escapeHtml(result.transfers.map(x => `${x.payer}|${x.receiver}|${x.hours}`).join("\n"))}</textarea></label><p class="inline-note ${result.checks.net_difference_is_zero ? "" : "warning"}">${balanceNotice}</p>${transferNotice}<div class="actions"><button class="secondary-button" id="validateTransfers">校验人工配平</button><button class="secondary-button" id="exportSettlementDraft">输出当前核算草案（含差值）</button><button class="secondary-button" id="exportPublicSettlement">输出人工转账配平公示表</button><button class="primary-button" id="exportSettlement">配平后输出最终转账 Excel</button><div class="output-picker-inline">${outputPickerMarkup()}</div><button class="ghost-button" id="backStep">返回修改官方下发工时</button></div>`;
}

function rosterStore() { try { return JSON.parse(localStorage.getItem("bookWorkbench.rosters") || "{}"); } catch (_) { return {}; } }
function refreshRosters() { const select = $("rosterSelect"); if (!select) return; const rosters = rosterStore(); select.innerHTML = `<option value="">载入已保存的阶段名单</option>` + Object.keys(rosters).sort().map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join(""); }
function updatePeopleCount() { const count = uniqueNames($("peopleInput")?.value || "").length; if ($("peopleCount")) $("peopleCount").textContent = count; }
function parseShifts(text) { const lines = lineParts(text); if (!lines.length) throw new Error("请至少录入一个班次，或先上传上一张成品排班表"); return lines.map((line, i) => { const pipe = line.split("|").map(x => x.trim()); if (pipe.length >= 4) return {name: pipe[0], start: timeText(pipe[1]), end: timeText(pipe[2]), duration_hours: duration(timeText(pipe[1]), timeText(pipe[2])), required_people: pipe[3] === "" ? NaN : Number(pipe[3]), id: pipe[4] || `shift_${i + 1}`}; const match = line.match(/^(.+?)\s+(\d{1,2}(?::\d{2})?)\s*(?:到|-|—|至)\s*(\d{1,2}(?::\d{2})?)\s*(\d+)\s*人?$/); if (!match) throw new Error(`无法识别班次：${line}`); const start = timeText(match[2]), end = timeText(match[3]); return {name: match[1].trim(), start, end, duration_hours: duration(start, end), required_people: Number(match[4]), id: ["morning", "afternoon", "evening"][i] || `shift_${i + 1}`}; }).map((shift, i) => { if (!shift.name || !/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/.test(shift.start) || !/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/.test(shift.end) || !Number.isFinite(shift.duration_hours) || shift.duration_hours <= 0 || !Number.isInteger(shift.required_people) || shift.required_people < 0) throw new Error(`第${i + 1}个班次的时间或人数不正确`); return shift; }); }
function parseConstraints(text) { return lineParts(text).map(line => { const [name, date, shift_id] = line.split("|").map(x => x.trim()); if (!name || !date || !shift_id) throw new Error(`无法识别硬约束：${line}`); return {name, date, shift_id}; }); }
function parseTargets(text) { const targets = {}; lineParts(text).forEach(line => { const clean = line.replace(/^\s*(?:\d+[.、)]|[-*])\s*/, "").trim(); const match = clean.match(/^(.+?)(?:\||\t|[：:=,，]|\s+)(\d+(?:\.\d+)?)\s*(?:小时|工时|h)?$/i); if (!match) throw new Error(`无法识别目标工时：${line}。请使用“姓名|8”“姓名 8小时”或“姓名：8工时”`); const name = match[1].trim(), hours = Number(match[2]); if (!name || !Number.isFinite(hours) || hours < 0) throw new Error(`目标工时不正确：${line}`); targets[name] = hours; }); return targets; }
function parseActualText(text) { const chunks = String(text || "").split(/[\n,，;；、]+/).map(x => x.trim()).filter(Boolean); const map = new Map(); chunks.forEach(chunk => { const match = chunk.match(/^(.+?)[\s|:：=]+(\d+(?:\.\d+)?)\s*(?:小时|工时|h)?$/i); if (!match) throw new Error(`无法识别实际工时：${chunk}`); const name = match[1].trim(), hours = Number(match[2]); if (!name || !Number.isFinite(hours) || hours < 0) throw new Error(`实际工时不正确：${chunk}`); if ([...map.keys()].some(key => nameKey(key) === nameKey(name))) throw new Error(`实际工时中姓名重复：${name}`); map.set(name, hours); }); if (!map.size) throw new Error("请先输入实际工时"); return [...map].map(([name, actual_hours]) => ({name, actual_hours, issued_hours: null})); }
function isHourLine(value) { return /^\d+(?:\.\d+)?\s*(?:小时|工时|h)?$/i.test(String(value || "").trim()); }
function parseVerticalHours(text, expectedCount) {
  const lines = lineParts(text);
  if (!lines.length) throw new Error("请先输入实际工时");
  if (lines.length !== expectedCount || !lines.every(isHourLine)) return null;
  return lines.map((line, index) => {
    const hours = parseHourNumber(line);
    if (!Number.isFinite(hours) || hours < 0) throw new Error(`第${index + 1}行实际工时不正确：${line}`);
    return hours;
  });
}
function updateActualInputHint() {
  const input = $("actualBulkInput"), hint = $("actualInputHint");
  if (!input || !hint) return;
  const lines = lineParts(input.value);
  hint.textContent = lines.length && lines.every(isHourLine) ? `　已识别 ${lines.length}/${state.settlement.rows.length} 行工时` : "";
}
function readTransfers() { return lineParts($("transferInput")?.value || "").map(line => { const [payer, receiver, hours] = line.split("|").map(x => x.trim()); return {payer, receiver, hours}; }); }
function friendlyTransferErrors(errors) { return (errors || []).map(error => { const text = String(error); const overall = text.match(/^overall difference is (.+);/); if (overall) return `总差额为 ${overall[1]} 小时：请返回上一步调整官方下发工时，或把它作为外部差额保留在核算草案中`; const payerPending = text.match(/^payer (.+) is not fully allocated$/); if (payerPending) return `${payerPending[1]} 应转出的工时还没有全部安排`; const receiverPending = text.match(/^receiver (.+) is not fully allocated$/); if (receiverPending) return `${receiverPending[1]} 应收的工时还没有全部安排`; const payerOver = text.match(/^payer (.+) is over-allocated$/); if (payerOver) return `${payerOver[1]} 填写的转出工时超过其应转出差额`; const receiverOver = text.match(/^receiver (.+) is over-allocated$/); if (receiverOver) return `${receiverOver[1]} 填写的转入工时超过其应收差额`; if (text === "paid and received totals do not match") return "转出工时与转入工时不一致"; return text; }); }
async function importFile(kind, input, callback) { const file = input?.files?.[0]; if (!file) throw new Error("请先选择文件"); if (window.workbenchBackend) { callback(await window.workbenchBackend.importFile(kind, file)); return; } const form = new FormData(); form.append("file", file); const response = await fetch(`/api/import/${kind}`, {method: "POST", body: form}); const data = await response.json(); if (!response.ok || data.ok === false) throw new Error(data.error || "文件读取失败"); callback(data); }
function applyTemplateDayRequirements(s, data) { const dateMap = {}; datesBetween(s.start, s.end).forEach(date => { dateMap[weekdayLabel(date)] = date; }); s.day_requirements = {}; Object.entries(data.day_requirements_by_weekday || {}).forEach(([weekday, shifts]) => { const date = dateMap[weekday]; if (date && shifts && typeof shifts === "object") s.day_requirements[date] = {...shifts}; }); }
function saveRoster() { const name = $("stageName").value.trim(), people = uniqueNames($("peopleInput").value); if (!name) throw new Error("请先填写阶段名单名称"); if (!people.length) throw new Error("请先填写当前人员"); const rosters = rosterStore(); rosters[name] = people; localStorage.setItem("bookWorkbench.rosters", JSON.stringify(rosters)); refreshRosters(); $("rosterSelect").value = name; }

function bindStepEvents() { if (state.mode === "schedule") bindScheduleEvents(); else bindSettlementEvents(); }
function bindScheduleEvents() {
  const s = state.schedule;
  if (state.step === "period") $("confirmSchedulePeriod")?.addEventListener("click", () => { const start = $("scheduleStart").value, end = $("scheduleEnd").value; if (!start || !end || end < start) return alert("请填写正确的开始和结束日期"); s.start = start; s.end = end; addMessage("user", `${start} 到 ${end}`); addMessage("assistant", "周期确认。接下来请确认每天有哪些班次、每个班次需要几个人。"); nextStep("shifts"); });
  if (state.step === "shifts") { $("importScheduleTemplate")?.addEventListener("click", async () => { try { await importFile("schedule-template", $("scheduleTemplateFile"), data => { s.shifts = data.shifts || []; s.people = (data.people || []).map(row => ({name: row.name, unavailable: [], preferred: [], target_hours: null})); applyTemplateDayRequirements(s, data); renderStep(); }); const exceptionCount = Object.keys(s.day_requirements).length; setStatus(`已读取${s.shifts.length}个班次${s.people.length ? `和${s.people.length}人名单` : ""}${exceptionCount ? `，保留${exceptionCount}天人数例外` : ""}`); } catch (e) { alert(e.message); } }); $("confirmShifts")?.addEventListener("click", () => { try { saveShiftEditor(s); addMessage("user", `已确认${s.shifts.length}个班次`); addMessage("assistant", "班次确认。接下来收集本周期实际参加的人员名单。"); nextStep("people"); } catch (e) { alert(e.message); } }); $("backStep")?.addEventListener("click", () => nextStep("period")); }
  if (state.step === "people") { updatePeopleCount(); $("peopleInput").addEventListener("input", updatePeopleCount); refreshRosters(); $("saveRoster")?.addEventListener("click", () => { try { saveRoster(); setStatus("阶段名单已保存"); } catch (e) { alert(e.message); } }); $("loadRoster")?.addEventListener("click", () => { const names = rosterStore()[$("rosterSelect").value] || []; if (!names.length) return alert("请选择已保存的阶段名单"); s.people = names.map(name => ({name, unavailable: [], preferred: [], target_hours: null})); $("peopleInput").value = names.join("\n"); updatePeopleCount(); }); $("importQuestionnaire")?.addEventListener("click", async () => { try { await importFile("questionnaire", $("questionnaireFile"), data => { const people = data.people || []; s.people = people.map(row => ({name: row.name, unavailable: [], preferred: [], target_hours: null, notes: row.notes || ""})); s.constraints = expandWeekdayRules(people, s.start, s.end); $("peopleInput").value = s.people.map(p => p.name).join("\n"); updatePeopleCount(); }); setStatus(`已读取${s.people.length}人问卷数据`); } catch (e) { alert(e.message); } }); $("confirmPeople")?.addEventListener("click", () => { const names = uniqueNames($("peopleInput").value); if (!names.length) return alert("请先填写本周期人员"); try { validateRosterNames(names); } catch(e) { return alert(e.message); } s.people = names.map(name => ({name, unavailable: [], preferred: [], target_hours: null})); addMessage("user", `已确认${names.length}人`); addMessage("assistant", "人员确认。接下来只处理已经确定的硬约束；临时想法不需要写进正式计算。"); nextStep("constraints"); }); $("backStep")?.addEventListener("click", () => nextStep("shifts")); }
  if (state.step === "constraints") { $("copyConstraintPrompt")?.addEventListener("click", async () => { try { await copyText($("constraintPrompt").value); setStatus("整理提示词已复制"); } catch (e) { alert(e.message); } }); $("confirmConstraints")?.addEventListener("click", () => { try { const gridConstraints = readConstraintGrid(); const textValue = $("constraintInput")?.value || ""; const initialText = s.constraints.map(x => `${x.name}|${x.date}|${x.shift_id}`).join("\n"); const textConstraints = textValue.trim() === initialText.trim() ? s.constraints.filter(rule => !ruleIsRepresented(s, rule)) : parseConstraints(textValue); const seen = new Set(); s.constraints = [...gridConstraints, ...textConstraints].filter(item => { const key = `${item.name}|${item.date}|${item.shift_id}`; if (seen.has(key)) return false; seen.add(key); return true; }); validateConfirmedRules(s); nextStep("plan"); } catch (e) { alert(e.message); } }); $("skipConstraints")?.addEventListener("click", () => { s.constraints = []; nextStep("plan"); }); $("backStep")?.addEventListener("click", () => nextStep("people")); }
  if (state.step === "plan") { $("plannedHoursHint").textContent = plannedHoursForSchedule(s); $("confirmPlan")?.addEventListener("click", () => { try { s.allocation_mode = $("allocationMode").value; s.targets = parseTargets($("targetInput").value); const payload = buildSchedulePayload(); setStatus("正在生成排班草稿"); api("/api/schedule/generate", payload).then(result => { s.result = result; addMessage("assistant", `排班草稿已经生成（${s.allocation_mode === "by_duration" ? "按班岗时长分别平均" : "按总工时平均"}）。现在请直接看表格、修改需要调整的人员，再做校验。`); nextStep("draft"); }).catch(e => { setStatus(e.message, true); alert(e.message); }); } catch (e) { alert(e.message); } }); $("backStep")?.addEventListener("click", () => nextStep("constraints")); }
  if (state.step === "draft") { $("validateSchedule")?.addEventListener("click", validateScheduleUi); $("exportSchedule")?.addEventListener("click", exportScheduleUi); $("backStep")?.addEventListener("click", () => nextStep("plan")); }
}
function buildSchedulePayload() {
  const s = state.schedule;
  validateRosterNames(s.people.map(p => p.name));
  validateConfirmedRules(s);
  const people = s.people.map(p => ({...p, target_hours: s.targets[p.name]}));
  return {cycle: {start_date: s.start, end_date: s.end}, days: datesBetween(s.start, s.end).map(date => ({date, label: `${weekdayLabel(date)} ${date}`})), shifts: s.shifts, people, constraints: s.constraints.map(x => ({...x})), day_requirements: s.day_requirements, allocation_mode: s.allocation_mode, assignments: []};
}
function syncSchedule() { if (!state.schedule.result) return null; const fields = [...document.querySelectorAll(".schedule-assignment")]; const s = state.schedule.result.schedule; s.assignments = s.days.flatMap((day, di) => s.shifts.map((shift, si) => { const index = di * s.shifts.length + si; const people = (fields[index]?.value || "").split(/[，,、\n]/).map(x => x.trim()).filter(Boolean); return {date: day.date, shift_id: shift.id, people}; })); return s; }
async function validateScheduleUi() { try { const payload = syncSchedule(), data = await api("/api/schedule/validate", payload); state.schedule.result = {schedule: payload, validation: data.validation}; renderStep(); setStatus(data.validation.ok ? "排班校验通过" : "排班存在异常", !data.validation.ok); if (!data.validation.ok) alert(data.validation.errors.join("\n")); } catch (e) { alert(e.message); } }
async function exportScheduleUi() { try { const payload = syncSchedule(), check = await api("/api/schedule/validate", payload); if (!check.validation.ok) { state.schedule.result.validation = check.validation; renderStep(); alert(check.validation.errors.join("\n")); return; } const out = await api("/api/export/schedule", {schedule: payload, validation: check.validation, output_dir: state.outputDir}); setStatus("排班 Excel 已输出"); showOutput(out.path, "排班表", out.download_url); } catch (e) { alert(e.message); } }

function parseHourNumber(value) { const match = String(value ?? "").trim().match(/^(\d+(?:\.\d+)?)\s*(?:小时|工时|h)?$/i); return match ? Number(match[1]) : NaN; }
function bindSettlementEvents() {
  const s = state.settlement;
  if (state.step === "period") $("confirmSettlementPeriod")?.addEventListener("click", () => { const start = $("settlementStart").value, end = $("settlementEnd").value; if (!start || !end || end < start) return alert("请填写正确的统计开始和结束日期"); s.start = start; s.end = end; addMessage("user", `${start} 到 ${end}`); addMessage("assistant", "统计时段确认。接下来先录入或上传本次结算人员名单。"); nextStep("people"); });
  if (state.step === "people") { $("settlementPeopleInput").addEventListener("input", () => { $("settlementPeopleCount").textContent = uniqueNames($("settlementPeopleInput").value).length; }); $("importSettlementRoster")?.addEventListener("click", async () => { try { await importFile("questionnaire", $("rosterFile"), data => { s.people = (data.people || []).map(row => row.name).filter(Boolean); $("settlementPeopleInput").value = s.people.join("\n"); $("settlementPeopleCount").textContent = s.people.length; }); setStatus(`已读取${s.people.length}人名单`); } catch (e) { alert(e.message); } }); $("confirmSettlementPeople")?.addEventListener("click", () => { const people = uniqueNames($("settlementPeopleInput").value); if (!people.length) return alert("请先录入或上传本次人员名单"); try { validateRosterNames(people); } catch(e) { return alert(e.message); } s.people = people; s.rows = alignRosterRows(people, s.rows); addMessage("user", `已确认${people.length}人名单`); addMessage("assistant", "人员确认。现在逐一输入每个人的实际到岗工时；输错可以直接改。"); nextStep("actual"); }); $("backStep")?.addEventListener("click", () => nextStep("period")); }
  if (state.step === "actual") {
    updateActualInputHint();
    $("actualBulkInput")?.addEventListener("input", updateActualInputHint);
    $("applyBulkActual")?.addEventListener("click", () => {
      try {
        const text = $("actualBulkInput").value;
        const vertical = parseVerticalHours(text, s.rows.length);
        if (vertical) {
          s.rows = s.rows.map((row, index) => ({...row, actual_hours: vertical[index]}));
        } else {
          const lines = lineParts(text);
          const numericLines = lines.length > 0 && lines.every(isHourLine);
          if (numericLines) throw new Error(`当前名单有${s.rows.length}人，但工时有${lines.length}行，请让两边人数完全一致`);
          const parsed = parseActualText(text);
          s.rows = applyActualRows(s.rows, parsed);
        }
        renderStep();
        setStatus("批量工时已按姓名顺序整理到表格");
      } catch (e) { alert(e.message); }
    });
    $("importAttendance")?.addEventListener("click", async () => {
      try {
        await importFile("settlement", $("attendanceFile"), data => {
          s.rows = applyActualRows(s.rows, data.rows || []);
        });
        renderStep();
        setStatus("已把签到统计匹配到本次名单");
      } catch (e) { alert(e.message); }
    });
    $("exportSummary")?.addEventListener("click", exportSummaryUi);
    $("confirmActual")?.addEventListener("click", () => {
      const fields = [...document.querySelectorAll(".actual-hour-input")];
      s.rows = s.rows.map((row, i) => ({...row, actual_hours: fields[i].value === "" ? null : Number(fields[i].value)}));
      if (s.rows.some(row => row.actual_hours === null)) return alert("请填写每个人的实际工时；如果确实没有上班，请填0");
      if (s.rows.some(row => !Number.isFinite(row.actual_hours) || row.actual_hours < 0)) return alert("实际工时必须是非负数字");
      addMessage("user", `已确认${s.rows.length}人的实际工时`);
      addMessage("assistant", "实际工时已确认。现在逐人确定本次官方下发工时。");
      nextStep("issued");
    });
    $("backStep")?.addEventListener("click", () => nextStep("people"));
  }
  if (state.step === "issued") { $("fillIssued33")?.addEventListener("click", () => { try { readIssuedCap(s); s.rows = s.rows.map(row => ({...row, issued_hours: s.cap})); renderStep(); } catch(e) { alert(e.message); } }); $("fillIssuedActual")?.addEventListener("click", () => { try { readIssuedCap(s); s.rows = s.rows.map(row => ({...row, issued_hours: Math.min(Number(row.actual_hours), s.cap)})); renderStep(); } catch(e) { alert(e.message); } }); $("calculateSettlement")?.addEventListener("click", async () => { const fields = [...document.querySelectorAll(".issued-input")]; s.rows = s.rows.map((row, i) => ({...row, issued_hours: fields[i].value === "" ? null : parseHourNumber(fields[i].value)})); if (s.rows.some(row => row.issued_hours === null || !Number.isFinite(row.issued_hours))) return alert("请填写每个人的官方下发工时，不能由系统猜测"); try { readIssuedCap(s); const data = await api("/api/settlement/calculate", {people: s.rows, issued_cap: s.cap}); s.result = data.result; addMessage("assistant", "差值已经算好。下面进入人工配平，你可以随时修改转账草案。"); nextStep("transfer"); } catch (e) { alert(e.message); } }); $("backStep")?.addEventListener("click", () => nextStep("actual")); }
  if (state.step === "transfer") { $("validateTransfers")?.addEventListener("click", validateTransfersUi); $("exportSettlementDraft")?.addEventListener("click", exportSettlementDraftUi); $("exportPublicSettlement")?.addEventListener("click", exportPublicSettlementUi); $("exportSettlement")?.addEventListener("click", exportSettlementUi); $("backStep")?.addEventListener("click", () => nextStep("issued")); }
}
function saveTransferValidation(check, transfers) { if (!state.settlement.result) return; state.settlement.result.transfers = transfers; state.settlement.result.transfer_validation = check; }
async function validateTransfersUi() { try { const transfers = readTransfers(); const data = await api("/api/settlement/validate-transfers", {people: state.settlement.rows, transfers, issued_cap: state.settlement.cap}); saveTransferValidation(data.result, transfers); renderStep(); if (!data.result.ok) { setStatus("转账草案尚未配平", true); alert(`当前还不能输出最终转账表：\n${friendlyTransferErrors(data.result.errors).join("\n")}\n\n你可以继续修改，或先输出“当前核算草案（含差值）”。`); } else { setStatus("修改后的转账校验通过"); alert("校验通过，可以输出最终转账表和公示表。"); } } catch (e) { alert(e.message); } }
async function exportSummaryUi() { try { const fields = [...document.querySelectorAll(".actual-hour-input")]; state.settlement.rows = state.settlement.rows.map((row, i) => ({...row, actual_hours: fields[i].value === "" ? null : parseHourNumber(fields[i].value)})); if (state.settlement.rows.some(row => row.actual_hours === null || !Number.isFinite(row.actual_hours) || row.actual_hours < 0)) return alert("请先填写每个人的实际工时；如果确实没有上班，请填0"); const out = await api("/api/export/settlement-summary", {period_start: state.settlement.start, period_end: state.settlement.end, people: state.settlement.rows, output_dir: state.outputDir}); setStatus("实际工时统计表已输出"); showOutput(out.path, "实际工时统计表", out.download_url); } catch (e) { alert(e.message); } }
async function exportSettlementDraftUi() { try { const transfers = readTransfers(); const check = await api("/api/settlement/validate-transfers", {people: state.settlement.rows, transfers, issued_cap: state.settlement.cap}); saveTransferValidation(check.result, transfers); const out = await api("/api/export/settlement", {period_start: state.settlement.start, period_end: state.settlement.end, issued_cap: state.settlement.cap, people: state.settlement.rows, settlement: state.settlement.result, transfers, transfer_validation: check.result, draft: true, output_dir: state.outputDir}); setStatus("当前核算草案已输出"); showOutput(out.path, "当前核算草案", out.download_url); } catch (e) { alert(e.message); } }
async function exportPublicSettlementUi() { try { const transfers = readTransfers(); const check = await api("/api/settlement/validate-transfers", {people: state.settlement.rows, transfers, issued_cap: state.settlement.cap}); saveTransferValidation(check.result, transfers); if (!check.result.ok) { renderStep(); alert(`当前还不能输出最终公示表：\n${friendlyTransferErrors(check.result.errors).join("\n")}\n\n请继续修改，或先输出“当前核算草案（含差值）”。`); return; } const out = await api("/api/export/settlement-public", {period_start: state.settlement.start, period_end: state.settlement.end, issued_cap: state.settlement.cap, people: state.settlement.rows, transfers, output_dir: state.outputDir}); setStatus("人工转账配平公示表已输出"); showOutput(out.path, "人工转账配平公示表", out.download_url); } catch (e) { alert(e.message); } }
async function exportSettlementUi() { try { const transfers = readTransfers(), check = await api("/api/settlement/validate-transfers", {people: state.settlement.rows, transfers, issued_cap: state.settlement.cap}); saveTransferValidation(check.result, transfers); if (!check.result.ok) { renderStep(); alert(`当前还不能输出最终转账表：\n${friendlyTransferErrors(check.result.errors).join("\n")}\n\n请继续修改，或先输出“当前核算草案（含差值）”。`); return; } const out = await api("/api/export/settlement", {period_start: state.settlement.start, period_end: state.settlement.end, issued_cap: state.settlement.cap, people: state.settlement.rows, settlement: state.settlement.result, transfers, transfer_validation: check.result, output_dir: state.outputDir}); setStatus("转账 Excel 已输出"); showOutput(out.path, "转账表", out.download_url); } catch (e) { alert(e.message); } }

function parseChatMode(text) { if (/转账|工资|实际工时/.test(text)) return "settlement"; if (/排班|班次|上岗/.test(text)) return "schedule"; return null; }
function parseChatDates(text) { const iso = text.match(/(\d{4}-\d{2}-\d{2})\s*(?:到|至|-|—)\s*(\d{4}-\d{2}-\d{2})/); if (iso) return [iso[1], iso[2]]; const cn = text.match(/(\d{1,2})月(\d{1,2})日?\s*(?:到|至|-|—)\s*(?:(\d{1,2})月)?(\d{1,2})日?/); if (!cn) return null; const year = new Date().getFullYear(), month = String(cn[1]).padStart(2, "0"), endMonth = String(cn[3] || cn[1]).padStart(2, "0"); return [`${year}-${month}-${String(cn[2]).padStart(2, "0")}`, `${year}-${endMonth}-${String(cn[4]).padStart(2, "0")}`]; }
function sendChat() { const text = $("chatInput").value.trim(); if (!text) return; addMessage("user", text); $("chatInput").value = ""; const detected = parseChatMode(text); if (!state.mode && detected) { setMode(detected, true); const dates = parseChatDates(text); if (dates) { if (detected === "schedule") { state.schedule.start = dates[0]; state.schedule.end = dates[1]; } else { state.settlement.start = dates[0]; state.settlement.end = dates[1]; } } renderStep(); return; } if (!state.mode) return addMessage("assistant", "请先说“做排班表”或“做转账表”。"); if (state.mode === "settlement" && state.step === "actual" && /\d/.test(text)) { $("actualBulkInput").value = `${$("actualBulkInput").value}\n${text}`.trim(); } else if ((state.mode === "schedule" || state.mode === "settlement") && state.step === "period") { const dates = parseChatDates(text); if (dates) { if (state.mode === "schedule") { state.schedule.start = dates[0]; state.schedule.end = dates[1]; } else { state.settlement.start = dates[0]; state.settlement.end = dates[1]; } renderStep(); addMessage("assistant", "我识别到时间范围了，请点击当前步骤的确认按钮。"); } } else addMessage("assistant", "我先把这句话留在对话里。请在当前步骤的输入区确认数据，再继续下一步，避免把未确认的想法直接写进报表。"); }
function renderSummary() { const target = $("workspaceSummary"); if (!state.mode) return; if (state.mode === "schedule") { const s = state.schedule; target.innerHTML = `<div class="summary-grid">${metric("当前阶段", "排班表")}${metric("人员", s.people.length ? `${s.people.length}人` : "未录入")}${metric("班次", s.shifts.length ? `${s.shifts.length}个` : "未确认")}${metric("状态", state.step === "draft" ? "待校验" : "逐步收集")}</div>`; } else { const s = state.settlement; const period = s.start && s.end ? `${s.start}—${s.end}` : "未确认"; target.innerHTML = `<div class="summary-grid">${metric("当前阶段", "转账表")}${metric("统计时段", period)}${metric("人员", s.people.length || s.rows.length ? `${s.people.length || s.rows.length}人` : "未录入")}${metric("状态", state.step === "transfer" ? "待确认输出" : "逐步收集")}</div>`; } }

if (typeof document !== "undefined") {

document.querySelectorAll(".mode-choice").forEach(button => button.addEventListener("click", () => setMode(button.dataset.mode)));
document.addEventListener("click", async event => { const button = event.target.closest("[data-action='choose-output-dir']"); if (!button || state.remoteMode) return; try { const response = await fetch("/api/choose-output-directory", {method: "POST"}); const data = await response.json(); if (data.ok && data.path) { state.outputDir = data.path; localStorage.setItem("bookWorkbench.outputDir", data.path); renderOutputLocation(); setStatus("已更改成品保存位置"); } } catch (e) { alert(e.message); } });
renderOutputLocation();
$("sendChat").addEventListener("click", sendChat); $("chatInput").addEventListener("keydown", event => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter") sendChat(); }); $("restartWork").addEventListener("click", restart);
(window.workbenchBackend ? window.workbenchBackend.request("/api/health") : fetch("/api/health").then(response => response.json())).then(data => { state.remoteMode = data.remote_mode === true; if (state.remoteMode) state.outputDir = ""; renderOutputLocation(); }).catch(error => { const node = $("runtimeStatus"); if (node) node.textContent = "计算组件暂未就绪，请点击重试。"; $("retryRuntime")?.classList.remove("hidden"); });

}

function nameKey(name) { return String(name ?? "").replace(/\s/g, ""); }
function validateRosterNames(names) {
  const seen = new Set();
  for (const name of names) {
    const key = nameKey(name);
    if (!key) throw new Error("名单中存在空姓名");
    if (seen.has(key)) throw new Error(`名单中姓名重复（空格视为同一姓名）：${name}`);
    seen.add(key);
  }
}
function expandWeekdayRules(people, start, end) {
  const dates = datesBetween(start, end);
  return people.flatMap(person => (person.unavailable_weekdays || []).flatMap(rule =>
    dates.filter(date => weekdayLabel(date) === rule.weekday.replace("周天", "周日"))
      .map(date => ({name: person.name, date, shift_id: rule.shift_id}))));
}
function ruleIsRepresented(s, rule) {
  return s.people.some(p => nameKey(p.name) === nameKey(rule.name)) && datesBetween(s.start, s.end).includes(rule.date) && s.shifts.some(shift => shift.id === rule.shift_id);
}
function validateConfirmedRules(s) {
  for (const rule of s.constraints) {
    if (!s.people.some(p => nameKey(p.name) === nameKey(rule.name))) throw new Error(`不可排规则的姓名不在本次名单：${rule.name}。请返回核对姓名，规则不会被自动忽略。`);
    if (!datesBetween(s.start, s.end).includes(rule.date)) throw new Error(`不可排日期不在当前周期：${rule.name} / ${rule.date}`);
    if (!s.shifts.some(shift => shift.id === rule.shift_id)) throw new Error(`不可排规则引用未知班次：${rule.shift_id}`);
  }
}
function alignRosterRows(names, previous) {
  validateRosterNames(names);
  const old = new Map(previous.map(row => [nameKey(row.name), row]));
  return names.map(name => ({actual_hours: null, issued_hours: null, ...old.get(nameKey(name)), name}));
}
function applyActualRows(roster, imported) {
  validateRosterNames(imported.map(row => row.name));
  const names = new Set(roster.map(row => nameKey(row.name)));
  const values = new Map();
  for (const row of imported) {
    if (!names.has(nameKey(row.name))) throw new Error(`上传的姓名不在本期名单：${row.name}。请核对后重试。`);
    const hours = parseHourNumber(row.actual_hours);
    if (!Number.isFinite(hours) || hours < 0) throw new Error(`${row.name} 的实际工时不是有效的非负数字`);
    values.set(nameKey(row.name), hours);
  }
  if (values.size !== roster.length) throw new Error(`本期 ${roster.length} 人，文件匹配了 ${values.size} 人。请补齐本期所有人的工时，没有上班填 0。`);
  return roster.map(row => ({...row, actual_hours: values.get(nameKey(row.name))}));
}
function readIssuedCap(s) {
  const cap = parseHourNumber($("issuedCap")?.value ?? s.cap);
  if (!Number.isFinite(cap) || cap < 0) throw new Error("请填写本次下发工时上限，例如 30、35 或 40");
  s.cap = cap;
}
function personalHoursMarkup(validation) {
  const shifts = state.schedule.shifts;
  const rows = validation.people.map(p => `<tr><td>${escapeHtml(p.name)}</td>${shifts.map(shift => `<td>${p.morning_or_shift_counts[shift.id] || 0}</td>`).join("")}<td><strong>${p.assigned_hours} h</strong></td></tr>`).join("");
  return `<details class="prompt-panel" open><summary>每个人的排班工时 · 修改后点“重新校验”更新</summary><div class="data-wrap"><table class="data-table"><thead><tr><th>姓名</th>${shifts.map(shift => `<th>${escapeHtml(shift.name)}次数</th>`).join("")}<th>合计工时</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
}
function defaultShifts() {
  return [
    {id: "morning", name: "早班", start: "09:00", end: "11:00", duration_hours: 2, required_people: 2},
    {id: "afternoon", name: "下午班", start: "14:00", end: "16:00", duration_hours: 2, required_people: 2},
    {id: "evening", name: "晚班", start: "19:00", end: "22:00", duration_hours: 3, required_people: 3},
  ];
}
function renderShiftEditor(s) {
  if (!s.shifts.length) s.shifts = defaultShifts();
  const definitions = s.shifts.map((shift, i) => `<tr><td><input aria-label="班次名称" class="shift-name" data-index="${i}" value="${escapeHtml(shift.name)}"></td><td><input aria-label="开始时间" class="shift-start" data-index="${i}" type="time" value="${escapeHtml(shift.start)}"></td><td><input aria-label="结束时间" class="shift-end" data-index="${i}" type="time" value="${escapeHtml(shift.end)}"></td><td><input aria-label="每日默认人数" class="shift-count" data-index="${i}" type="number" min="0" step="1" value="${shift.required_people}"></td></tr>`).join("");
  const daily = datesBetween(s.start, s.end).map(date => `<tr><th>${weekdayLabel(date)}<br><small>${date}</small></th>${s.shifts.map(shift => `<td><input class="day-count" aria-label="${date} ${escapeHtml(shift.name)}需要人数" type="number" min="0" step="1" data-date="${date}" data-shift="${escapeHtml(shift.id)}" value="${requiredPeopleForDate(s, date, shift)}"></td>`).join("")}</tr>`).join("");
  return `<div class="data-wrap"><table class="data-table"><thead><tr><th>班次</th><th>开始</th><th>结束</th><th>每日默认人数</th></tr></thead><tbody>${definitions}</tbody></table></div><div class="actions"><button class="secondary-button" data-editor="apply-defaults">将默认人数应用到每天</button></div><p class="inline-note">下表是本次实际采用的人数，每一天都可以不同。0 表示这个时段不设岗位。晚班默认 19:00–22:00。</p><div class="data-wrap" style="margin-top:12px"><table class="data-table"><thead><tr><th>日期</th>${s.shifts.map(shift => `<th>${escapeHtml(shift.name)}人数</th>`).join("")}</tr></thead><tbody>${daily}</tbody></table></div><details class="prompt-panel"><summary>读取旧排班表 / 编辑更多班次</summary><div class="prompt-panel-body"><p class="inline-note">旧表只作为班次和名单的起点。读入后请再次确认日期与人数。</p><div class="actions"><input id="scheduleTemplateFile" type="file" accept=".xlsx,.csv"><button class="secondary-button" id="importScheduleTemplate">读取成品排班表结构</button></div><label class="field">每行：班次名|开始|结束|人数|编号<textarea id="shiftInput">${escapeHtml(s.shifts.map(shift => `${shift.name}|${shift.start}|${shift.end}|${shift.required_people}|${shift.id}`).join("\n"))}</textarea></label><button class="secondary-button" data-editor="apply-text">应用这些班次</button></div></details><div class="actions"><button class="primary-button" id="confirmShifts">确认每天岗位，下一步</button><button class="ghost-button" id="backStep">返回上一步</button></div>`;
}
function saveShiftEditor(s, useDefaults = false) {
  const names = [...document.querySelectorAll(".shift-name")];
  const starts = [...document.querySelectorAll(".shift-start")];
  const ends = [...document.querySelectorAll(".shift-end")];
  const counts = [...document.querySelectorAll(".shift-count")];
  const shifts = parseShifts(s.shifts.map((shift, i) => `${names[i].value}|${starts[i].value}|${ends[i].value}|${counts[i].value}|${shift.id}`).join("\n"));
  const requirements = {};
  if (!useDefaults) {
    for (const field of document.querySelectorAll(".day-count")) {
      const count = field.value === "" ? NaN : Number(field.value);
      if (!Number.isInteger(count) || count < 0) throw new Error(`${field.dataset.date} 的需要人数必须是非负整数`);
      (requirements[field.dataset.date] ||= {})[field.dataset.shift] = count;
    }
  }
  s.shifts = shifts; s.day_requirements = requirements;
}
if (typeof document !== "undefined") {
  document.addEventListener("input", event => {
    const field = event.target;
    // Save edits as they happen, so going back never reconstructs empty rows.
    const index = Number(field.dataset?.index);
    if (field.classList.contains("actual-hour-input")) state.settlement.rows[index].actual_hours = field.value === "" ? null : parseHourNumber(field.value);
    if (field.classList.contains("issued-input")) state.settlement.rows[index].issued_hours = field.value === "" ? null : parseHourNumber(field.value);
    if (field.id === "issuedCap") state.settlement.cap = field.value;
    if (field.id === "transferInput" && state.settlement.result) {
      state.settlement.result.transfers = readTransfers();
      delete state.settlement.result.transfer_validation;
    }
    if (field.classList.contains("schedule-assignment")) {
      delete state.schedule.result.balance_report;
      const notice = $("balanceNotice"); if (notice) notice.textContent = "草稿已修改，请重新校验并更新工时统计。";
      const button = $("exportSchedule"); if (button) button.disabled = true;
      setStatus("排班已修改，请重新校验");
    }
  });
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-editor]");
    if (!button) return;
    try {
      if (button.dataset.editor === "apply-defaults") saveShiftEditor(state.schedule, true);
      if (button.dataset.editor === "apply-text") state.schedule.shifts = parseShifts($("shiftInput").value);
      renderStep();
    } catch(error) { alert(error.message); }
  });
}

function balanceNoticeMarkup(result) {
  const f = result.validation.fairness;
  if (!f) return "";
  const report = result.balance_report;
  let message = "重新校验会更新每个人的工时。";
  if (report?.status === "optimal_spread") message = `已验证当前已排岗位的最小工时差为 ${formatNumber(f.hour_spread)} h。${report.duration_counts_floor_ceil ? "各时长班岗次数也已达到平均数的向下或向上取整范围。" : ""}`;
  if (report?.status === "personal_targets") message = "已按你填写的个人目标生成草稿，本次未求所有人工时相同。";
  if (report?.status === "search_limit") message = "本次未在计算预算内确认最优均衡，保留可校验的草稿。这不表示更平均的方案不存在。";
  return `<div class="summary-grid">${metric("最低工时", f.minimum_hours + " h")}${metric("最高工时", f.maximum_hours + " h")}${metric("最大工时差", f.hour_spread + " h")}</div><p id="balanceNotice" class="inline-note ${report?.status === "search_limit" ? "warning" : ""}">${escapeHtml(message)}</p>`;
}
