import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { COMMON_ZONES, blankDraft, draftChanged, draftFromTask, firstProblemSection, inputFromDraft, sectionsWithProblems, timezoneChoices, validateDraft, zoneLabel } from "../src/routine-form.mjs";
import { parsePriceText } from "../src/price-lines.mjs";
import { TASKS } from "../tools/shots/fixtures/routines.mjs";
import { EXTRA_TASKS } from "../tools/shots/fixtures/routines.mjs";

// The request bodies the old form sent, recorded from the old UI on the same fixtures (tools/shots/fixtures/routine-bodies-baseline.json).
const baseline = JSON.parse(readFileSync(new URL("../tools/shots/fixtures/routine-bodies-baseline.json", import.meta.url), "utf8"));
const body = (sent) => JSON.parse(sent.find((request) => request.method !== "GET" && /\/tasks(\/|$)/.test(request.path)).body);
const BOT = { finbot: "b0000000-0000-4000-8000-000000000001", newsbot: "b0000000-0000-4000-8000-000000000002", applebot: "b0000000-0000-4000-8000-000000000003" };

test("opening an existing task and saving it as it is sends what the old form sent for it, key for key (8 tasks)", () => {
  const tasks = [...TASKS, ...EXTRA_TASKS];
  assert.equal(tasks.length, 8);
  for (const task of tasks) {
    const old = baseline.edit[task.name];
    assert.ok(old, task.name);
    const input = inputFromDraft(draftFromTask(task, { fallbackBotId: BOT.finbot }));
    // The one task whose price line was kept as text: the old form dropped it (price_lines: []); the rows keep it, and refuse to send it until it is a line (see below).
    if (task.name === "旧式价格线") { assert.deepEqual(body(old.sent).config.price_lines, []); assert.deepEqual(validateDraft(draftFromTask(task)).map((p) => p.field), ["priceRows:2"]); continue; }
    assert.equal(JSON.stringify(input), JSON.stringify(body(old.sent)), task.name);
    assert.deepEqual(validateDraft(draftFromTask(task)), [], task.name);
  }
});

test("the old form's new-task bodies, from the same inputs (10 recorded cases)", () => {
  const make = (patch) => ({ ...blankDraft({ botId: BOT.finbot }), ...patch });
  const cases = {
    briefDefault: make({ instruction: "总结今天的新闻" }),
    briefEverything: make({ botId: BOT.applebot, name: "  AAPL 周报  ", schedule: "every", everyValue: "2", everyUnit: "weeks", time: "09:15", countMode: "count", runs: "3", timezone: "Europe/Paris", scope: "symbols", symbols: ["AAPL", "MSFT", "NVDA", "TSLA"], instruction: "写详细一点", skill: "s3000000-0000-4000-8000-000000000001" }),
    briefHourly: make({ name: "整点看盘", schedule: "hourly", time: "00:20", countMode: "once" }),
    briefDaily: make({ name: "每日", schedule: "daily", time: "21:00", timezone: "America/New_York" }),
    briefSymbolsDaily: make({ name: "公司名单", scope: "symbols", symbols: ["NVDA"], instruction: "x" }),
    alertPlain: make({ name: "只看申报", kind: "alerts" }),
    alertPrice3: make({ name: "三条价格线", kind: "alerts", filings: false, news: false, telegram: true, priceRows: parsePriceText("NVDA>150, AAPL<180, tsla > 200.5"), scope: "symbols", symbols: ["NVDA", "AAPL", "TSLA"] }),
    alertPriceSpaces: make({ name: "空格", kind: "alerts", priceRows: parsePriceText("  NVDA  >  150 , AAPL<180"), countMode: "count", runs: "2" }),
    alertBothSides: make({ name: "同一代码两边", kind: "alerts", priceRows: parsePriceText("NVDA>150, NVDA<120") }),
    alertEvery: make({ botId: BOT.newsbot, name: "每三小时", kind: "alerts", schedule: "every", everyValue: "3", everyUnit: "hours", time: "10:00", priceRows: parsePriceText("AAPL<180") }),
  };
  for (const [name, draft] of Object.entries(cases)) {
    assert.deepEqual(validateDraft(draft), [], name);
    assert.equal(JSON.stringify(inputFromDraft(draft)), JSON.stringify(body(baseline.create[name].sent)), name);
  }
});

test("a bot's own page fixes the bot whatever the draft says (the old form's `botId ?? draftBot`)", () => {
  const input = inputFromDraft({ ...blankDraft({ botId: BOT.finbot }), instruction: "x" }, { lockedBotId: BOT.applebot });
  assert.equal(JSON.stringify(input), JSON.stringify(body(baseline.botPage.create.sent)).replace(/"name":"本 bot 简报"/, '"name":"研究队列简报"'));
});

test("the old form's rules, all of them at once (it stopped at the first); the sentences are the old ones", () => {
  const bad = { ...blankDraft(), name: "  ", scope: "symbols", symbols: [], kind: "alerts", priceRows: parsePriceText("NVDA>=150"), schedule: "every", everyValue: "0", countMode: "count", runs: "2.5", time: "" };
  const problems = validateDraft(bad);
  assert.deepEqual(problems.map((p) => p.field), ["name", "everyValue", "time", "runs", "symbols", "priceRows:0"]);
  assert.deepEqual(problems.map((p) => p.section), ["basics", "time", "time", "time", "scope", "content"]);
  assert.equal(problems[0].message, baseline.createValidation.noName.alert[0]);
  assert.equal(problems[4].message, baseline.createValidation.symbolsEmpty.alert[0]);
  assert.equal(problems[1].message, "间隔要填整数，至少为 1。");
  assert.equal(problems[3].message, "执行次数要填整数，至少为 1。");
  assert.deepEqual(sectionsWithProblems(problems), ["basics", "time", "scope", "content"]);
  assert.equal(firstProblemSection(problems), "basics");
  assert.equal(firstProblemSection([]), null);
});

test("each rule on its own, with the edge the old form had", () => {
  const ok = { ...blankDraft(), name: "x" };
  assert.deepEqual(validateDraft(ok), []);
  assert.equal(validateDraft({ ...ok, name: "名".repeat(81) }).length, 1);
  assert.equal(validateDraft({ ...ok, name: "名".repeat(80) }).length, 0);
  assert.equal(validateDraft({ ...ok, schedule: "every", everyValue: "1.5" }).length, 1);
  assert.equal(validateDraft({ ...ok, schedule: "every", everyValue: "" }).length, 1);
  assert.equal(validateDraft({ ...ok, schedule: "daily", everyValue: "0" }).length, 0); // the interval only counts when the schedule is 每隔一段时间
  assert.equal(validateDraft({ ...ok, countMode: "count", runs: "0" }).length, 1);
  assert.equal(validateDraft({ ...ok, countMode: "once", runs: "0" }).length, 0);
  assert.equal(validateDraft({ ...ok, scope: "symbols", symbols: ["AAPL"] }).length, 0);
  assert.equal(validateDraft({ ...ok, kind: "brief", priceRows: parsePriceText("NVDA>=150") }).length, 0); // price lines only count for an alert
  assert.equal(validateDraft({ ...ok, kind: "alerts", priceRows: [] }).length, 0);
});

test("a task whose time zone is not in any list shows it and keeps it", () => {
  const task = EXTRA_TASKS.find((t) => t.timezone === "Pacific/Chatham");
  const draft = draftFromTask(task);
  assert.equal(draft.timezone, "Pacific/Chatham");
  assert.equal(inputFromDraft(draft).timezone, "Pacific/Chatham");
  const rare = timezoneChoices(["Asia/Shanghai", "Europe/Paris", "Asia/Tokyo"], "Pacific/Chatham");
  assert.equal(rare.kept, "Pacific/Chatham");
  assert.ok(!rare.pinned.includes("Pacific/Chatham") && !rare.rest.includes("Pacific/Chatham"));
  const known = timezoneChoices(["Asia/Shanghai", "Europe/Paris", "Pacific/Chatham"], "Pacific/Chatham");
  assert.equal(known.kept, null);
  assert.ok(known.rest.includes("Pacific/Chatham"));
});

test("the usual zones come first (once), the rest follow, UTC and the default are always offered", () => {
  const choices = timezoneChoices(["Africa/Cairo", "Asia/Shanghai", "Europe/London", "Asia/Tokyo", "Zulu"], "Asia/Shanghai");
  assert.deepEqual(choices.pinned.slice(0, 2), ["Asia/Shanghai", "Asia/Tokyo"]);
  assert.ok(choices.pinned.includes("UTC") && choices.pinned.every((zone) => COMMON_ZONES.includes(zone)));
  assert.deepEqual(choices.rest, ["Africa/Cairo", "Zulu"]);
  assert.equal(new Set([...choices.pinned, ...choices.rest]).size, choices.pinned.length + choices.rest.length);
  const none = timezoneChoices(undefined, "Asia/Shanghai");
  assert.ok(none.pinned.includes("Asia/Shanghai") && none.rest.length === 0 && none.kept === null);
  assert.equal(zoneLabel("Asia/Hong_Kong"), "Asia/Hong Kong");
});

test("the draft counts as changed when a field or a price line differs; a price row typed in another case or with spaces is the same line", () => {
  const task = TASKS[2];
  const initial = draftFromTask(task);
  assert.equal(draftChanged(initial, draftFromTask(task)), false);
  assert.equal(draftChanged({ ...initial, name: "别的" }, initial), true);
  assert.equal(draftChanged({ ...initial, priceRows: parsePriceText("nvda > 140 , AAPL<190") }, initial), false);
  assert.equal(draftChanged({ ...initial, priceRows: parsePriceText("NVDA>141, AAPL<190") }, initial), true);
  assert.equal(draftChanged({ ...initial, symbols: [...initial.symbols, "MSFT"] }, initial), true);
});

test("a task of another kind than the draft's: the fields of the other kind are not sent (the old form's rule)", () => {
  const brief = inputFromDraft({ ...blankDraft(), kind: "brief", filings: false, telegram: true, priceRows: parsePriceText("A>1"), instruction: "i", skill: "s" });
  assert.equal(brief.channel, "inbox"); assert.deepEqual(brief.config, {}); assert.equal(brief.instruction, "i"); assert.equal(brief.skill_id, "s");
  const alerts = inputFromDraft({ ...blankDraft(), kind: "alerts", telegram: true, instruction: "i", skill: "s" });
  assert.equal(alerts.channel, "telegram"); assert.equal(alerts.instruction, null); assert.equal(alerts.skill_id, "");
  assert.equal(inputFromDraft({ ...blankDraft(), scope: "research_queue", symbols: ["AAPL"] }).symbols.length, 0);
  assert.equal(inputFromDraft({ ...blankDraft(), countMode: "unlimited" }).max_runs, 0);
});
