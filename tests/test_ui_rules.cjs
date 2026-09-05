const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const context = vm.createContext({localStorage: {getItem: () => null}});
vm.runInContext(fs.readFileSync('workbench/static/app.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
const plain = value => JSON.parse(JSON.stringify(value));

test('R3 repeats a Monday restriction across both weeks, and accepts 周天', () => {
  const rules = run(String.raw`expandWeekdayRules([{name:'甲',unavailable_weekdays:[{weekday:'周一',shift_id:'morning'},{weekday:'周天',shift_id:'evening'}]}],'2026-09-07','2026-09-20')`);
  assert.deepEqual(plain(rules).map(rule => rule.date), ['2026-09-07', '2026-09-14', '2026-09-13', '2026-09-20']);
});
test('R4 unknown names block generation, confirmed complete rules reach Python', () => {
  run(String.raw`Object.assign(state.schedule,{start:'2026-09-07',end:'2026-09-07',people:[{name:'甲'}],shifts:defaultShifts(),constraints:[{name:'未知',date:'2026-09-07',shift_id:'morning'}]})`);
  assert.throws(() => run('buildSchedulePayload()'), /姓名不在/);
  run(String.raw`state.schedule.constraints[0].name='甲'`);
  assert.equal(run('buildSchedulePayload().constraints.length'), 1);
  assert.equal(run('buildSchedulePayload().days[0].label'), '周一 2026-09-07');
});
test('returning and reordering the roster preserves hours by name', () => {
  const rows = plain(run(String.raw`alignRosterRows(['乙','小 王','新成员'],[{name:'小王',actual_hours:40,issued_hours:35},{name:'乙',actual_hours:20,issued_hours:25}])`));
  assert.deepEqual(rows.map(r => [r.actual_hours, r.issued_hours]), [[20,25],[40,35],[null,null]]);
});
test('imports reject unknown, repeated or missing names instead of dropping rows', () => {
  assert.throws(() => run(String.raw`applyActualRows([{name:'甲'}],[{name:'乙',actual_hours:5}])`), /不在本期名单/);
  assert.throws(() => run(String.raw`applyActualRows([{name:'甲'}],[{name:'甲',actual_hours:1},{name:'甲',actual_hours:2}])`), /重复/);
  assert.throws(() => run(String.raw`applyActualRows([{name:'甲'},{name:'乙'}],[{name:'甲',actual_hours:1}])`), /请补齐/);
  assert.throws(() => run(String.raw`parseActualText('甲 1\n甲 2')`), /重复/);
});
test('vertical hours match the roster count exactly, including zero', () => {
  assert.deepEqual(plain(run(String.raw`parseVerticalHours('0\n35',2)`)), [0,35]);
  assert.equal(run(String.raw`parseVerticalHours('0\n35',3)`), null);
});
test('evening is 19 to 22 and daily staffing affects the deterministic total', () => {
  assert.equal(run('defaultShifts()[2].start'), '19:00');
  assert.equal(run('defaultShifts()[2].duration_hours'), 3);
  assert.equal(run(String.raw`plannedHoursForSchedule({start:'2026-09-07',end:'2026-09-07',shifts:defaultShifts(),day_requirements:{'2026-09-07':{evening:5}}})`), 23);
  assert.throws(() => run(String.raw`parseShifts('早班|25:00|28:00|2|morning')`), /时间或人数/);
});
