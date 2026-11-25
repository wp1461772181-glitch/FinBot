import assert from "node:assert/strict";
import test from "node:test";
import {
  allTicked, anyTicked, applicationGroups, applicationLine, applicationRows, applyBody, countThings, countsLine, createdLine, leaveOutOf, nameOfKey, previewMarks, removedLine,
  resultLines, skillWarnings, stillThereLine, templateKeys, templateLabel, templateWriteError, undoLeaveOut, undoTicked, usualRows, whenText, zoneText,
} from "../src/role-templates.mjs";

// The shapes are the plan's appendix (短线), written the way the server is assumed to send them.
const short = {
  id: "short_term", label: "短线", blurb: "看日内和几天内的走势", notes: ["盯防类的几条会在每次回答和值班判断时读到。"],
  memory: [{ key: "st_about", kind: "about_me", text: "我主要做短线。" }, { key: "st_conclusion_first", kind: "instruction", text: "回答先给结论和关键价位。" }],
  briefs: [{ key: "st_premarket", name: "盘前速览", schedule_kind: "weekdays", schedule_time: "09:00", timezone: "America/New_York", instruction: "开盘前给我一份速览", skill_key: "st_skill_premarket" }],
  skills: [{ key: "st_skill_premarket", name: "盘前速览", description: "d", body: "b", output_template: "o", allowed_tools: ["query_portfolio"] }, { key: "st_skill_why", name: "异动归因", description: "d", body: "b", output_template: "o", allowed_tools: [] }],
  usual: ["st_skill_premarket", "st_skill_why", "新闻摘要"],
};
const dca = { id: "dca", label: "定投", memory: [{ key: "dca_about", text: "x" }], briefs: [{ key: "dca_monthly", name: "每月定投复盘", schedule_kind: "every", every_value: 30, every_unit: "days", schedule_time: "10:00", timezone: "Asia/Shanghai" }], skills: [] };

test("a template's label and the count line follow the locale", () => {
  assert.equal(templateLabel("短线"), "短线");
  assert.equal(templateLabel("短线", "en-US"), "Short-term");
  assert.equal(templateLabel("基金经理", "en-US"), "Fund manager");
  assert.equal(templateLabel("我的模板", "en-US"), "我的模板");
  assert.equal(templateLabel(undefined), "");
  assert.equal(countsLine(short), "2 条记忆 · 1 个简报 · 2 个技能");
  assert.equal(countsLine(short, "en-US"), "2 memory items · 1 brief · 2 skills");
  assert.equal(countsLine(null), "0 条记忆 · 0 个简报 · 0 个技能");
});

test("when a brief runs: the existing schedule words and the zone in plain words", () => {
  assert.equal(whenText(short.briefs[0]), "工作日 09:00 · 纽约时间");
  assert.equal(whenText(short.briefs[0], "en-US"), "Weekdays 09:00 · New York time");
  assert.match(whenText(dca.briefs[0]), /^每 30 .+（从 10:00 起） · 北京时间$/);
  assert.equal(zoneText("Europe/Paris"), "Europe/Paris");
  assert.equal(zoneText("Etc/Some_Zone"), "Etc/Some Zone");
  assert.equal(whenText(null), "");
});

test("every part starts ticked, and the unticked keys are the body's leave_out in the template's order", () => {
  const ticked = allTicked(short);
  assert.deepEqual([...ticked], ["st_about", "st_conclusion_first", "st_premarket", "st_skill_premarket", "st_skill_why"]);
  assert.deepEqual(leaveOutOf(short, ticked), []);
  ticked.delete("st_premarket"); ticked.delete("st_about");
  assert.deepEqual(leaveOutOf(short, ticked), ["st_about", "st_premarket"]);
  assert.equal(anyTicked(short, ticked), true);
  assert.equal(anyTicked(short, new Set()), false);
  assert.deepEqual(templateKeys(null), { memory: [], briefs: [], skills: [], all: [] });
});

test("usual skills: the template's own that are ticked, then the built-in names, which have no checkbox", () => {
  const ticked = allTicked(short);
  assert.deepEqual(usualRows(short, ticked), [
    { key: "st_skill_premarket", name: "盘前速览", builtin: false }, { key: "st_skill_why", name: "异动归因", builtin: false }, { key: "新闻摘要", name: "新闻摘要", builtin: true },
  ]);
  ticked.delete("st_skill_why");
  assert.deepEqual(usualRows(short, ticked).map(row => row.name), ["盘前速览", "新闻摘要"]);
  assert.deepEqual(usualRows({ ...short, usual: undefined }, ticked), []);
});

test("a brief ticked without the skill it follows gets a sentence that says so; nothing else does", () => {
  const ticked = allTicked(short);
  assert.deepEqual(skillWarnings(short, ticked), []);
  ticked.delete("st_skill_premarket");
  const [line] = skillWarnings(short, ticked);
  assert.match(line, /简报「盘前速览」要按技能「盘前速览」的步骤做/);
  assert.match(skillWarnings(short, ticked, "en-US")[0], /follows the skill "盘前速览", which is not ticked/);
  ticked.delete("st_premarket");
  assert.deepEqual(skillWarnings(short, ticked), []);
});

test("the preview's reuse and skip lines mark keys; a line with no key (a whole part) marks none but still shows", () => {
  const preview = { reuse: [{ key: "st_about", reason: "已有，沿用" }], skip: [{ key: "st_premarket", reason: "已有同名任务" }, { key: "", reason: "这一层记忆已有 28 条，再加 5 条会超过 30 条；先删几条或少勾几条" }, "st_skill_why"], will_create: ["x"] };
  const marks = previewMarks(preview);
  assert.deepEqual([...marks.keys()], ["st_about", "st_premarket", "st_skill_why"]);
  assert.deepEqual(marks.get("st_about"), { kind: "reuse", reason: "已有，沿用" });
  assert.deepEqual(marks.get("st_skill_why"), { kind: "skip", reason: "" });
  const lines = resultLines(preview.skip, short);
  assert.deepEqual(lines.map(l => l.name), ["盘前速览", "", "异动归因"]);
  assert.equal(lines[1].key, "");
  assert.match(lines[1].reason, /超过 30 条/);
  assert.deepEqual(previewMarks(null).size, 0);
  assert.deepEqual(resultLines("nope", short), []);
  assert.equal(nameOfKey(short, "st_about"), "我主要做短线。");
  assert.equal(nameOfKey(short, "nothing"), "");
});

test("counting what a server list holds: lists, numbers and objects of those", () => {
  assert.equal(countThings([1, 2, 3]), 3);
  assert.equal(countThings(4), 4);
  assert.equal(countThings({ a: [1], b: 2, c: { d: [1, 2] } }), 5);
  assert.equal(countThings(null), 0);
  assert.equal(countThings("x"), 0);
  assert.equal(countThings(Number.NaN), 0);
});

test("what an apply wrote, and nothing when nothing new was written", () => {
  assert.equal(createdLine({ profile_item_ids: ["a", "b"], task_ids: ["t"], skill_ids: ["s", "u"], usual_added: ["s", "u", "z"] }), "2 条记忆 · 1 个简报 · 2 个技能");
  assert.equal(createdLine({ profile_item_ids: ["a"], task_ids: [], skill_ids: [] }, "en-US"), "1 memory item · 0 briefs · 0 skills");
  assert.equal(createdLine({ profile_item_ids: [], task_ids: [], skill_ids: [], usual_added: ["x"] }), "");
  assert.equal(createdLine(null), "");
});

test("an application line: in use or taken back, with the day and where", () => {
  const a = { id: "1", label: "短线", applied_at: "2026-11-26T03:00:00Z", undone_at: null, bot_id: null, bot_name: null };
  assert.equal(applicationLine(a), "在用：短线 · 11月26日 · 全局");
  assert.equal(applicationLine(a, "en-US"), "In use: Short-term · 11/26 · Global");
  assert.equal(applicationLine({ ...a, bot_id: "b1", bot_name: "盯盘" }), "在用：短线 · 11月26日 · 盯盘");
  assert.equal(applicationLine({ ...a, bot_id: "b1", bot_name: null }), "在用：短线 · 11月26日 · 已删除的 bot");
  assert.equal(applicationLine({ ...a, undone_at: "2026-11-27T03:00:00Z" }), "已撤掉：短线 · 11月26日 · 全局");
});

test("applications are grouped: in use first (newest first), then those taken back", () => {
  const groups = applicationGroups([
    { id: "old", applied_at: "2026-11-01T00:00:00Z", undone_at: null }, { id: "gone", applied_at: "2026-11-20T00:00:00Z", undone_at: "2026-11-21T00:00:00Z" }, { id: "new", applied_at: "2026-11-25T00:00:00Z", undone_at: null }, null,
  ]);
  assert.deepEqual(groups.live.map(a => a.id), ["new", "old"]);
  assert.deepEqual(groups.undone.map(a => a.id), ["gone"]);
  assert.deepEqual(applicationGroups(undefined), { live: [], undone: [] });
});

test("what of an application is still there, from the counts", () => {
  assert.equal(stillThereLine({ still_there: { profile_items: 2, tasks: 1, skills: 2, usual: 3 } }), "还在：2 条记忆 · 1 个简报 · 2 个技能");
  assert.equal(stillThereLine({ still_there: { profile_items: 1 } }, "en-US"), "Still there: 1 memory item · 0 briefs · 0 skills");
  assert.equal(stillThereLine({ still_there: {} }), "都已不在了");
  assert.equal(stillThereLine({ still_there: { usual: 1 } }), "还在：0 条记忆 · 0 个简报 · 0 个技能");
  assert.equal(stillThereLine(null, "en-US"), "None of it is left");
});

test("the undo dialog lists the things in the order memory, briefs, skills, usual; what is gone is not ticked and never sent", () => {
  const application = { items: [
    { id: "s1", part: "skill", text: "盘前速览" }, { id: "m1", part: "memory", text: "我改过的字" }, { id: "t1", part: "brief", text: "盘前速览", gone: true }, { id: "u1", part: "usual", text: "盘前速览" }, { part: "memory", text: "no id" }, null,
  ] };
  const rows = applicationRows(application);
  assert.deepEqual(rows.map(r => r.id), ["m1", "t1", "s1", "u1"]);
  assert.equal(rows[0].text, "我改过的字");
  assert.equal(rows[1].gone, true);
  const ticked = undoTicked(rows);
  assert.deepEqual([...ticked].sort(), ["m1", "s1", "u1"]);
  assert.deepEqual(undoLeaveOut(rows, ticked), []);
  ticked.delete("m1");
  assert.deepEqual(undoLeaveOut(rows, ticked), ["m1"]);
  assert.deepEqual(applicationRows({}), []);
  assert.deepEqual(applicationRows(null), []);
});

test("what an undo did", () => {
  assert.equal(removedLine({ removed: ["a", "b", "c"], gone: ["d"] }), "撤掉了 3 项，另有 1 项已经不在了");
  assert.equal(removedLine({ removed: { profile_items: ["a"], tasks: ["t"] }, gone: [] }), "撤掉了 2 项");
  assert.equal(removedLine({ removed: [], gone: ["d"] }), "另有 1 项已经不在了");
  assert.equal(removedLine({ removed: [1], gone: [2, 3] }, "en-US"), "Removed 1 item; 2 items were already gone");
  assert.equal(removedLine({ removed: [], gone: [] }), "");
});

test("the request body: no bot is 全局 + 助理; leave_out is always a list", () => {
  assert.deepEqual(applyBody(null, ["a"]), { bot_id: null, leave_out: ["a"] });
  assert.deepEqual(applyBody("", undefined), { bot_id: null, leave_out: [] });
  assert.deepEqual(applyBody("bot-1", []), { bot_id: "bot-1", leave_out: [] });
});

test("a refused request says its reason in Chinese: the code's words, or the server's own sentence as given", () => {
  assert.equal(templateWriteError(422, "unknown_bot"), "这个 bot 已不存在，换一个范围再试。");
  assert.equal(templateWriteError(404, "unknown_template"), "没有这个模板。");
  assert.equal(templateWriteError(409, "memory_full"), "这一层的记忆已满，先删几条或少勾几条。");
  assert.equal(templateWriteError(409, "too_many_tasks"), "例行任务已到上限，先删掉几个或不勾简报。");
  assert.equal(templateWriteError(409, "这一层记忆已有 28 条，再加 5 条会超过 30 条；先删几条或少勾几条"), "这一层记忆已有 28 条，再加 5 条会超过 30 条；先删几条或少勾几条");
  assert.equal(templateWriteError(409, { code: "memory_full" }), "这一层的记忆已满，先删几条或少勾几条。");
  assert.equal(templateWriteError(403, undefined), "登录个人聊天后才能使用模板。");
  assert.equal(templateWriteError(404, "something_else"), "这一项已不存在。");
  assert.equal(templateWriteError(500, undefined), "没有成功，请重试。");
  assert.equal(templateWriteError(undefined, null), "没有成功，请重试。");
});
