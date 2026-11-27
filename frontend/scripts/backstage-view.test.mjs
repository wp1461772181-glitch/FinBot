import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  ANSWER_FILTER_DEFAULTS, answerRow, answerNotes, answersQuery, answerStatus, costCell, deliveryRow, detailTimeline, dutyDelivery, dutyModeLine, helperLines, dutyRow, FEEDBACK_CHOICES, FEEDBACK_FAILED, feedbackBody, formatMs, formatTime, formatTokens, formatUsd, operationRow, pagedQuery,
  RECONCILE_NOTE, reconcileBlock, answerFeedbackBlock, EARLY_RUN, qualityWeekRow, badAnswerRow, rulerRunRow, slowRuleText, usageGroupLabel, usageQuery, usageRange, usageRow, usageTotalsRow,
  MEMORY_BYS, MEMORY_CHANGES, MEMORY_FILTER_DEFAULTS, MEMORY_GONE, MEMORY_NOTE, MEMORY_TARGETS, memoryQuery, memoryRow,
} from "../src/backstage-view.mjs";
import { ANSWERS, DELIVERIES, DETAIL, DUTY, HELPERS, DETAIL_INCOMPLETE, DETAIL_OLD, OPERATIONS, usageAnswer } from "../tools/shots/fixtures/backstage.mjs";

const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");

test("the answers query carries only the filters that are set, and 'only high tier' and 'only slow' are the API's tier=high and slow=1", () => {
  assert.equal(answersQuery(ANSWER_FILTER_DEFAULTS), "");
  assert.equal(answersQuery({ ...ANSWER_FILTER_DEFAULTS, botId: "b1", engine: "v2", status: "failed", highTier: true, slow: true, q: " 营收 ", before: "1.x" }),
    "?bot_id=b1&engine=v2&status=failed&tier=high&slow=1&q=%E8%90%A5%E6%94%B6&before=1.x");
  assert.equal(answersQuery({ ...ANSWER_FILTER_DEFAULTS, q: "x".repeat(150) }), `?q=${"x".repeat(100)}`, "the API takes 100 characters at most");
  assert.equal(pagedQuery("abc"), "?before=abc");
  assert.equal(pagedQuery(null), "");
});

test("statuses read in words, incomplete included; an unknown one is shown as it came", () => {
  assert.deepEqual(answerStatus("succeeded"), { label: "已回答", kind: "success" });
  assert.deepEqual(answerStatus("failed"), { label: "失败", kind: "failure" });
  assert.deepEqual(answerStatus("cancelled"), { label: "已取消", kind: "neutral" });
  assert.deepEqual(answerStatus("waiting_for_input"), { label: "等你回复", kind: "action" });
  assert.deepEqual(answerStatus("incomplete"), { label: "没有完成", kind: "failure" });
  assert.deepEqual(answerStatus("zzz"), { label: "zzz", kind: "neutral" });
});

test("cost: a number is a dollar figure; null with calls is 未设价格, never a made-up number; no calls is a dash", () => {
  assert.deepEqual(costCell(0.0123, true), { kind: "amount", amount: "$0.0123" });
  assert.deepEqual(costCell(0.5, true), { kind: "amount", amount: "$0.50" });
  assert.deepEqual(costCell(0, true), { kind: "amount", amount: "$0.00" });
  assert.deepEqual(costCell(null, true), { kind: "unpriced", amount: "" });
  assert.deepEqual(costCell(null, false), { kind: "none", amount: "" });
  // The server's own word for the state wins: rows still being written are 记账中, never 未设价格.
  assert.deepEqual(costCell(null, true, "pending"), { kind: "pending", amount: "" });
  assert.deepEqual(costCell(0.01, true, "pending"), { kind: "pending", amount: "" }, "a partial sum of a turn still being booked is not its cost");
  assert.deepEqual(costCell(null, true, "unpriced"), { kind: "unpriced", amount: "" });
  assert.deepEqual(costCell(0.02, true, "unpriced"), { kind: "amount", amount: "$0.0200" });
  assert.deepEqual(costCell(null, true, "none"), { kind: "none", amount: "" });
  assert.deepEqual(costCell(0.5, true, "priced"), { kind: "amount", amount: "$0.50" });
  // Nothing was booked (older than the ledger, or rows lost): not a missing price, so not 未设价格.
  assert.deepEqual(costCell(null, true, "unrecorded"), { kind: "unrecorded", amount: "" });
  assert.equal(formatUsd(1234.5), "$1,234.50");
  assert.equal(formatUsd(0.00004), "$0.00004");
});

test("durations and token counts", () => {
  assert.equal(formatMs(null), "—");
  assert.equal(formatMs(850), "850 ms");
  assert.equal(formatMs(2500), "2.5 s");
  assert.equal(formatMs(61500), "1 min 2 s");
  assert.equal(formatTokens(null), "—");
  assert.equal(formatTokens(1870), "1,870");
  assert.equal(formatTokens(1234567), "1,234,567");
  assert.equal(formatTime("2026-11-13T01:50:02+00:00", "UTC"), "11-13 01:50");
  assert.equal(formatTime(null, "UTC"), "—");
  assert.equal(formatTime("nonsense", "UTC"), "—");
});

test("answers tab: each sample row becomes the cells the table shows", () => {
  const rows = ANSWERS.items.map((row) => answerRow(row, "UTC"));
  assert.equal(rows.length, 5);
  assert.deepEqual(rows[0], { id: ANSWERS.items[0].message_id, time: "11-13 01:50", bot: "FinBot", question: "TSLA 最近一个季度的营收是多少？", status: { label: "已回答", kind: "success" }, tier: "低档",
    time_taken: "4.2 s", calls: "2", tokens: "1,870", cost: { kind: "amount", amount: "$0.0123" }, old_engine: false, feedback: "" });
  assert.equal(rows[1].status.label, "等你回复");
  assert.equal(rows[1].tier, "中档");
  assert.equal(rows[2].tier, "高档");
  assert.deepEqual(rows[2].cost, { kind: "unpriced", amount: "" }, "cost null on a turn that called models: 未设价格");
  assert.deepEqual(answerRow({ ...ANSWERS.items[2], cost_state: undefined }, "UTC").cost, { kind: "unpriced", amount: "" }, "an answer from before cost_state existed behaves as it did");
  assert.equal(rows[2].time_taken, "1 min 2 s");
  assert.equal(rows[3].status.label, "没有完成");
  assert.deepEqual(rows[3].cost, { kind: "pending", amount: "" }, "the incomplete sample's ledger rows have not landed: 记账中");
  assert.equal(rows[3].tier, "—");
  assert.equal(rows[3].time_taken, "—");
  assert.equal(rows[4].old_engine, true, "an old-engine row says so");
  assert.deepEqual(rows[4].cost, { kind: "none", amount: "" }, "no model call is recorded for it, so no cost either");
  assert.equal(rows[4].tokens, "—");
});

test("a row whose bot is gone and a question that is empty still have something to show", () => {
  const row = answerRow({ ...ANSWERS.items[0], bot_name: null, question: "" }, "UTC");
  assert.equal(row.bot, "—");
  assert.equal(row.question, "（没有问题文字）");
});

test("slow rule text names the threshold; without a threshold it says nothing was slow enough to judge", () => {
  assert.equal(slowRuleText(2400), "慢的标准：耗时高于本页回答的 90 分位（2.4 s）");
  assert.equal(slowRuleText(null), "");
});

test("detail: an ordered record is interleaved by its events, each with its offset; the question, card, card result and answer frame it", () => {
  const steps = detailTimeline(DETAIL, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "model", "model", "narration", "tool", "tool", "tool", "model", "narration", "card", "card_result", "answer"]);
  const [, first, second, narration, tool1, , tool3, third] = steps;
  assert.equal(first.title, "haiku-5.5");
  assert.equal(first.offset, "", "an attempt the timeline does not know has no time of its own");
  assert.equal(second.offset, "+1.7 s");
  assert.equal(narration.offset, "+1.7 s");
  assert.equal(tool1.offset, "+1.7 s");
  assert.equal(tool1.done_offset, "+2.4 s", "a tool shows when its result came back");
  assert.equal(tool3.done_offset, "", "no tool_done: the call did not finish");
  assert.equal(third.offset, "+4.4 s");
  assert.equal(first.tier, "低档");
  assert.equal(first.ok, false);
  assert.equal(first.error, "http_500");
  assert.equal(second.attempt, 2, "a retry shows as its own row");
  assert.equal(second.cost.kind, "amount");
  assert.equal(first.cost.kind, "none", "a failed call that used no tokens has no cost to show");
  assert.equal(third.tokens, "3,080");
  assert.equal(third.cost.kind, "unpriced", "tokens without a price: 未设价格");
  const tools = steps.filter((s) => s.kind === "tool");
  assert.equal(tools[0].title, "研究队列");
  assert.equal(tools[0].result, "成功，共 7 条：AAPL、TSLA、NVDA");
  assert.equal(tools[1].arguments, '{"symbol":"ANT"}');
  assert.equal(tools[1].result, "失败：needs_confirmation");
  assert.equal(tools[2].result, "没有结果记录");
  assert.equal(tools[2].state, "unfinished");
  const card = steps.find((s) => s.kind === "card");
  assert.equal(card.title, "确认以下操作");
  assert.deepEqual(card.targets, ["ANT · 加入研究队列"]);
  assert.deepEqual(card.choices, ["同意", "取消"], "the card's choices are shown as labels only");
  assert.equal(steps.find((s) => s.kind === "card_result").title, "已完成");
  assert.equal(steps.at(-1).text, "我已提出这个操作，等你在卡片上确认。");
});

test("detail without events (an old record, or one from before the field) keeps the kind order and shows no offsets", () => {
  const { events, ordered, ...older } = DETAIL;
  const steps = detailTimeline(older, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "narration", "narration", "model", "model", "model", "tool", "tool", "tool", "card", "card_result", "answer"]);
  assert.ok(steps.every((s) => !s.offset));
  const unordered = detailTimeline({ ...DETAIL, ordered: false, events: [] }, "UTC");
  assert.deepEqual(unordered.map((s) => s.kind), steps.map((s) => s.kind));
});

test("events that point at nothing are skipped and what they left out still shows", () => {
  const steps = detailTimeline({ ...DETAIL, events: [{ kind: "narration", at_ms: 5, index: 99 }, { kind: "tool_done", at_ms: 6, call_id: "nope" }, { kind: "model_call", at_ms: 7, index: 2 }, "x", null] }, "UTC");
  assert.deepEqual(steps.filter((s) => s.kind === "model").length, 3, "every model call is shown once");
  assert.equal(steps.filter((s) => s.kind === "tool").length, 3);
  assert.equal(steps.filter((s) => s.kind === "narration").length, 2);
});

test("detail notes: backup model, the old-engine line, an unfinished turn, the Langfuse link", () => {
  assert.deepEqual(answerNotes(DETAIL).map((n) => n.text), ["改用备用模型：haiku-5.5 → gpt-6.1-terra（http_500）", "未设价格的调用缺：输入价、输出价"]);
  assert.equal(answerNotes({ ...DETAIL, cost_state: "priced" }).length, 1);
  assert.equal(answerNotes(DETAIL_OLD)[0].text, "旧流程的记录，只有部分经过");
  assert.equal(answerNotes(DETAIL_INCOMPLETE)[0].text, "这一轮没有答完，下面是它留下的记录");
  assert.equal(answerNotes({ ...DETAIL, latest_known: ["NVDA", "AMD"] }).find((n) => n.kind === "latest_known").text, "系统带上了：NVDA、AMD");
  assert.equal(answerNotes({ ...DETAIL, latest_known: [] }).some((n) => n.kind === "latest_known"), false);
  assert.equal(answerNotes(DETAIL).some((n) => n.kind === "langfuse"), false, "the link is its own field, not a note");
  assert.equal(answerNotes({ ...DETAIL, ordered: false, events: [{}, {}] }).some((n) => n.text === "这条记录没有时间顺序，按类别排列"), true);
  assert.equal(answerNotes({ ...DETAIL, ordered: false, events: [] }).some((n) => n.kind === "unordered"), false, "nothing to order, nothing to say");
  assert.equal(answerNotes({ ...DETAIL, ordered: undefined }).some((n) => n.kind === "unordered"), false, "an answer from before the field is not accused of being unordered");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "pending" }).find((n) => n.kind === "pending").text, "记账中：有些调用的费用还在写入，稍后再看");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "unpriced", missing_prices: ["input", "cache_read"] }).find((n) => n.kind === "unpriced").text, "未设价格的调用缺：输入价、缓存读取价");
});

test("detail of an old-engine record is a short timeline, not an error", () => {
  const steps = detailTimeline(DETAIL_OLD, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "answer"]);
  const unfinished = detailTimeline(DETAIL_INCOMPLETE, "UTC");
  assert.deepEqual(unfinished.map((s) => s.kind), ["question", "model", "tool"], "no answer step when no answer was given");
  assert.equal(unfinished[2].result, "没有结果记录");
});

test("detail copes with missing parts (null, wrong types)", () => {
  const steps = detailTimeline({ question: "q", model_calls: null, narration: "x", tool_calls: [null, { name: 5 }], card: "x", answer: null }, "UTC");
  assert.deepEqual(steps.map((s) => s.kind), ["question", "tool"]);
  assert.deepEqual(detailTimeline(null, "UTC"), []);
});

test("usage: ranges are UTC days; 7 days ends today and starts six days before", () => {
  assert.deepEqual(usageRange(7, "2026-11-13"), { from: "2026-11-07", to: "2026-11-13" });
  assert.deepEqual(usageRange(30, "2026-11-13"), { from: "2026-10-15", to: "2026-11-13" });
  assert.equal(usageQuery({ from: "2026-11-01", to: "2026-11-03", group: "model" }), "?from=2026-11-01&to=2026-11-03&group=model");
  assert.equal(usageQuery({ from: "", to: "", group: "day" }), "?group=day");
});

test("usage rows: tokens, p50, cost, and which prices are missing", () => {
  const payload = usageAnswer("day");
  const rows = payload.groups.map((g) => usageRow(g, "day"));
  assert.deepEqual(rows[0], { key: "2026-11-11", label: "2026-11-11", calls: "31", failed: "1", input: "82,000", output: "9,100", cache: "40,000 / 6,000", p50: "1.8 s", cost: { kind: "amount", amount: "$0.31" }, missing: [], unpriced_calls: 0 });
  assert.deepEqual(rows[1].missing, ["缓存读取价", "缓存写入价"]);
  assert.equal(rows[1].unpriced_calls, 6);
  assert.equal(rows[1].cost.kind, "amount", "priced calls are still summed; the unpriced count and the missing prices come beside it");
  const byModel = usageAnswer("model").groups.map((g) => usageRow(g, "model"));
  assert.deepEqual(byModel[2].cost, { kind: "unpriced", amount: "" });
  assert.deepEqual(byModel[2].missing, ["缓存读取价", "缓存写入价", "输入价", "输出价"], "in the order the API names them (sorted by key)");
  const totals = usageTotalsRow(payload.totals);
  assert.equal(totals.label, "合计");
  assert.equal(totals.calls, "101");
  assert.equal(totals.unpriced_calls, 6);
});

test("usage labels: purposes and the no-bot group are readable; day, model and bot keep what the API says", () => {
  assert.equal(usageGroupLabel("purpose", { key: "judge", label: "judge" }), "核查");
  assert.equal(usageGroupLabel("purpose", { key: "material_analysis", label: "material_analysis" }), "材料分析");
  assert.equal(usageGroupLabel("purpose", { key: "something_new", label: "something_new" }), "something_new");
  assert.equal(usageGroupLabel("bot", { key: "none", label: "（无）" }), "（无）");
  assert.equal(usageGroupLabel("model", { key: "haiku-5.5", label: "haiku-5.5" }), "haiku-5.5");
  assert.equal(usageGroupLabel("day", { key: "2026-11-11", label: "2026-11-11" }), "2026-11-11");
});

test("operations: what, status, decided at, result; a lapsed card nobody touched says 已过期，未处理", () => {
  const rows = OPERATIONS.items.map((o) => operationRow(o, "UTC"));
  assert.equal(rows[0].what, "确认以下操作");
  assert.equal(rows[0].detail, "加入研究队列 · ANT 加入研究队列");
  assert.deepEqual(rows[0].status, { label: "已完成", kind: "success" });
  assert.equal(rows[0].decided_at, "11-13 01:22");
  assert.equal(rows[0].result, "成功");
  assert.deepEqual(rows[1].status, { label: "已过期，未处理", kind: "neutral" });
  assert.equal(rows[1].decided_at, "—");
  assert.equal(rows[1].result, "—");
  assert.deepEqual(rows[2].status, { label: "已取消", kind: "neutral" });
  assert.equal(rows[3].result, "失败：invalid_price");
  const pressedLate = operationRow({ ...OPERATIONS.items[1], decided_at: "2026-11-12T13:00:00+00:00" }, "UTC");
  assert.equal(pressedLate.status.label, "已过期", "a lapsed card somebody pressed is expired, not 'untouched'");
  assert.equal(operationRow({ ...OPERATIONS.items[1], expired: false }, "UTC").status.label, "等待确认");
});

test("deliveries: time, source, channel, status, acknowledged", () => {
  const rows = DELIVERIES.items.map((d) => deliveryRow(d, "UTC"));
  assert.deepEqual(rows[0], { id: DELIVERIES.items[0].id, time: "11-13 01:00", source: "提醒", channel: "Telegram", status: { label: "已发送", kind: "success" }, acked: "11-13 01:05", text: "NVDA 上穿了你设的 125 美元价格线。", feedback: null });
  assert.equal(rows[1].source, "任务");
  assert.equal(rows[1].channel, "微信");
  assert.equal(rows[1].acked, "未确认");
  assert.deepEqual(rows[2].status, { label: "发送失败", kind: "failure" });
  assert.equal(rows[2].acked, "—");
  assert.deepEqual(rows[3].status, { label: "过期未发", kind: "failure" });
  assert.deepEqual(rows[4].status, { label: "等待发送", kind: "progress" });
  assert.deepEqual(deliveryRow({ ...DELIVERIES.items[0], status: "sent", failure: "partial", source: "x", channel: "y" }, "UTC").status, { label: "部分送达", kind: "action" });
  assert.equal(deliveryRow({ ...DELIVERIES.items[0], source: "x", channel: "y" }, "UTC").source, "x", "an unknown source is shown as it came");
});

test("deliveries: the kernel's duty messages and its morning brief read in words", () => {
  assert.equal(deliveryRow({ ...DELIVERIES.items[0], source: "duty" }, "UTC").source, "值班");
  assert.equal(deliveryRow({ ...DELIVERIES.items[0], source: "brief" }, "UTC").source, "早间简报");
});

test("deliveries: the WeChat copy of a sentinel alert reads 盯盘提醒 and asks for no 有用／没用", () => {
  const row = deliveryRow({ ...DELIVERIES.items[0], source: "sentinel", channel: "wechat", group_id: "g-1" }, "UTC");
  assert.equal(row.source, "盯盘提醒");
  assert.equal(row.channel, "微信");
  assert.equal(row.feedback, null);
});

test("deliveries: 有用／没用 only on duty and brief rows, by their group (their own id without one), pressed as the API says", () => {
  const base = { ...DELIVERIES.items[0], id: "row-1", group_id: "g-1" };
  assert.deepEqual(deliveryRow({ ...base, source: "duty", feedback: "useful" }, "UTC").feedback, { group: "g-1", verdict: "useful" });
  assert.deepEqual(deliveryRow({ ...base, source: "brief", feedback: "not_useful" }, "UTC").feedback, { group: "g-1", verdict: "not_useful" });
  assert.deepEqual(deliveryRow({ ...base, source: "duty", feedback: null }, "UTC").feedback, { group: "g-1", verdict: null }, "nothing pressed yet");
  assert.deepEqual(deliveryRow({ ...base, source: "brief", group_id: null }, "UTC").feedback, { group: "row-1", verdict: null });
  assert.deepEqual(deliveryRow({ ...base, source: "duty", feedback: "maybe" }, "UTC").feedback, { group: "g-1", verdict: null }, "an unknown verdict is not shown pressed");
  for (const source of ["notify", "routine", "reply", "x"]) assert.equal(deliveryRow({ ...base, source, feedback: "useful" }, "UTC").feedback, null, source);
  assert.deepEqual(FEEDBACK_CHOICES, [{ verdict: "useful", label: "有用" }, { verdict: "not_useful", label: "没用" }]);
  assert.equal(FEEDBACK_FAILED, "没记上");
  assert.deepEqual(feedbackBody("g-1", "useful"), { target: "outbox", target_id: "g-1", verdict: "useful" });
  assert.deepEqual(feedbackBody("g-1", "not_useful"), { target: "outbox", target_id: "g-1", verdict: "not_useful" });
});

test("deliveries tab: the buttons are plain buttons that show which one is pressed, and a failed request says 没记上", () => {
  const tab = src("app/backstage/DeliveriesTab.tsx");
  assert.match(tab, /aria-pressed=\{current === choice\.verdict\}/);
  assert.match(tab, /chosen\[group\] \?\? row\.feedback\.verdict/, "a press on this page wins over the verdict the list was read with");
  assert.match(tab, /if \(!row\.feedback\) return null;/, "no buttons on a row without feedback");
  assert.match(tab, /failed\[group\] && <span role="status"[^>]*>\{t\(FEEDBACK_FAILED\)\}<\/span>/);
  assert.match(tab, /setChosen\(state => \(\{ \.\.\.state, \[group\]: verdict \}\)\);\s*\} catch \{\s*setFailed/s, "pressed only once the server took it");
  assert.match(src("api/backstage.ts"), /requestJson<[^>]+>\("\/api\/backstage\/feedback", \{\s*method: "POST"/);
});

test("the page is wired in: route, owner-only navigation, and its one write is 有用／没用", () => {
  const sidebar = src("app/shell/AppSidebar.tsx"), more = src("app/shell/MoreDrawer.tsx"), router = src("app/router.tsx");
  assert.match(sidebar, /\{props\.personal && <NavLeaf area="backstage" props=\{props\} \/>\}/, "the entry is the owner's");
  assert.match(more, /props\.personal && .*paths\.backstage\(\)/s, "the phone's 更多 lists it for the owner only");
  assert.match(router, /PATTERNS\.backstageTab/);
  assert.match(router, /PATTERNS\.backstage,/);
  const api = src("api/backstage.ts");
  assert.deepEqual(api.match(/method:\s*"(POST|PUT|PATCH|DELETE)"/g), ['method: "POST"'], "the only write is the feedback POST");
  assert.match(api, /"\/api\/backstage\/feedback", \{\s*method: "POST"/);
  for (const file of ["BackstagePage", "AnswersTab", "AnswerDrawer", "UsageTab", "OperationsTab", "DeliveriesTab"]) assert.doesNotMatch(src(`app/backstage/${file}.tsx`), /method:\s*"(POST|PUT|PATCH|DELETE)"|<form|type="submit"/, file);
});

test("free text cannot widen a table or the drawer, reads in its own direction, and the 未设价格 link does not open the row", () => {
  const table = src("app/backstage/BackstageTable.tsx"), drawer = src("app/backstage/AnswerDrawer.tsx");
  assert.match(table, /\[overflow-wrap:anywhere\]/);
  assert.match(table, /<span dir="auto"/);
  assert.match(table, /onClick=\{event => event\.stopPropagation\(\)\}/);
  assert.match(drawer, /\[overflow-wrap:anywhere\]/);
  assert.ok((drawer.match(/dir="auto"/g) ?? []).length >= 5);
  assert.match(drawer, /load\.data\?\.id === id/, "a detail is shown only under the id it was asked for");
  assert.match(src("app/backstage/UsageTab.tsx"), /load\.data\.group === group && load\.data\.from === range\.from && load\.data\.to === range\.to/, "usage numbers only under their own request");
  assert.match(src("app/backstage/use-paged.ts"), /items: \[\], next: null, extra: null, loading: true/, "a new filter clears the old rows at once");
});

test("unrecorded: a list row and a detail line say nothing was booked, never 未设价格; the detail explains it", () => {
  assert.deepEqual(answerRow({ ...ANSWERS.items[0], cost_usd: null, cost_state: "unrecorded" }, "UTC").cost, { kind: "unrecorded", amount: "" });
  const lines = detailTimeline({ ...DETAIL_INCOMPLETE, model_calls: [{ ...DETAIL_INCOMPLETE.model_calls[0], recorded: false }, { ...DETAIL_INCOMPLETE.model_calls[0] }] }, "UTC").filter((s) => s.kind === "model");
  assert.equal(lines[0].cost.kind, "unrecorded", "a call with no ledger row");
  assert.equal(lines[1].cost.kind, "unpriced", "a call with a row and no price");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "unrecorded", missing_prices: [] }).find((n) => n.kind === "unrecorded").text, "这一轮没有记账（早于记账功能，或记账丢失）");
  assert.equal(answerNotes({ ...DETAIL, cost_state: "unrecorded" }).some((n) => n.kind === "unpriced"), false);
});

test("number cells never wrap, so long text beside them cannot squeeze them", () => {
  for (const file of ["AnswersTab", "UsageTab"]) assert.ok((src(`app/backstage/${file}.tsx`).match(/whitespace-nowrap/g) ?? []).length >= 5, file);
  assert.match(src("app/backstage/BackstageTable.tsx"), /font-mono tabular-nums whitespace-nowrap|whitespace-nowrap font-mono tabular-nums/);
});


test("duty: each decision and each way a wake-up ends has its word, and only a sent-or-not message says so", () => {
  const rows = DUTY.items.map((item) => dutyRow(item, "UTC"));
  assert.deepEqual(rows.map((row) => row.decision.label), ["告诉你", "攒进简报", "只记下", "不理会", "告诉你", "告诉你", "告诉你", "失败", "没有决定", "丢弃", "已关闭"]);
  assert.deepEqual(rows.map((row) => row.delivery), ["", "", "", "", "已发出", "超过今天的上限，没发", "发送失败", "", "", "", ""]);
  assert.deepEqual(rows.slice(0, 1).map((row) => [row.symbol, row.what, row.open, row.mode]), [["NVDA", "NVDA 盘中下跌 6.2%，跌破 20 日均线", DETAIL.message_id, "只观察"]]);
  assert.equal(rows[4].mode, "已开启");
  assert.equal(rows[10].mode, "已关闭");
  assert.equal(rows[7].open, null, "a wake-up with no recorded turn has nothing to open");
  assert.equal(rows[1].message, "");
  assert.deepEqual(dutyRow({}, "UTC").decision, { label: "—", kind: "neutral" });
});

test("duty: a tell_now held over the night is not a failed send", () => {
  assert.equal(dutyDelivery({ decision: "tell_now", delivery: "held_night" }), "夜里压住，没发");
  assert.equal(dutyDelivery({ decision: "tell_now", delivery: "briefed" }), "已随早间简报发出");
  assert.equal(dutyDelivery({ decision: "tell_now", delivery: "telegram_not_bound" }), "发送失败");
});

test("duty: the mode line says the mode in the owner's words, and an unknown mode says nothing", () => {
  assert.equal(dutyModeLine("shadow"), "现在只观察：它会判断，但不会发消息给你。");
  assert.equal(dutyModeLine("on"), "已开启：『告诉你』的会按你的通道设置发出。");
  assert.equal(dutyModeLine("off"), "已关闭");
  assert.equal(dutyModeLine("???"), "");
  assert.equal(usageGroupLabel("purpose", { key: "duty", label: "duty" }), "值班");
});

test("helpers: one plain line each (model, steps, what it read, finished or not, how long); nothing when there are none", () => {
  assert.deepEqual(helperLines(DETAIL), []);
  assert.deepEqual(helperLines({ helpers: [] }), []);
  assert.deepEqual(helperLines(undefined), []);
  assert.deepEqual(helperLines({ ...DETAIL, helpers: HELPERS }).map((h) => h.text), [
    "小助手 · haiku-5.5 · 3 步 · 读了 已披露财务数字、搜索已配置新闻源 · 已做完 · 18.0 s",
    "小助手 · deepseek-flash · 6 步 · 读了 SEC 申报 · 未做完 · 2 min 0 s"]);
  assert.deepEqual(helperLines({ helpers: [{ call_id: "x", model: "m", steps: 1, complete: true, seconds: 2, tools: [] }] }).map((h) => h.text), ["小助手 · m · 1 步 · 已做完 · 2.0 s"], "no tools read: no 读了");
  assert.equal(helperLines({ helpers: [{ call_id: "x", complete: false }] })[0].complete, false);
});


// ---- 5d-1: the figure check ----------------------------------------------------------------------------------------

test("「数字没对上」 is the API's reconcile=flagged, sent only when it is ticked", () => {
  assert.equal(ANSWER_FILTER_DEFAULTS.reconcileFlagged, false);
  assert.equal(answersQuery({ ...ANSWER_FILTER_DEFAULTS, reconcileFlagged: true }), "?reconcile=flagged");
  assert.equal(answersQuery({ ...ANSWER_FILTER_DEFAULTS, slow: true, reconcileFlagged: true, q: "x" }), "?slow=1&reconcile=flagged&q=x");
});

test("the detail's figure check: how many were checked, each flagged line with its values, and the fixed note under them", () => {
  const block = reconcileBlock({ ...DETAIL, reconciliation: { state: "flagged", figures: 3, error: null,
    flagged: [{ line: "利润是 8888 美元，现金是 9999 美元", values: ["8888", "9999"] }, { line: "", values: ["1"] }, "junk"] } });
  assert.deepEqual(block, { kind: "flagged", title: "数字对账结果", checked: "查过的数字：3", text: "",
    lines: [{ line: "利润是 8888 美元，现金是 9999 美元", values: "8888、9999" }], note: RECONCILE_NOTE });
  assert.equal(RECONCILE_NOTE, "这些数字在这一轮读到的资料里都找不到；不一定是错，可能是模型自己的知识或算法，请对照原文判断。");
});

test("a clean check says so with no note; a failed one names its error; an unchecked answer shows no block", () => {
  assert.deepEqual(reconcileBlock({ ...DETAIL, reconciliation: { state: "clean", figures: 2, flagged: [], error: null } }),
    { kind: "clean", title: "数字对账结果", checked: "查过的数字：2", text: "没有找不到出处的数字。", lines: [], note: "" });
  assert.deepEqual(reconcileBlock({ ...DETAIL, reconciliation: { state: "error", figures: null, flagged: [], error: "KeyError" } }),
    { kind: "error", title: "数字对账结果", checked: "", text: "对账没有做完：KeyError", lines: [], note: "" });
  assert.equal(reconcileBlock({ ...DETAIL, reconciliation: null }), null);
  assert.equal(reconcileBlock(DETAIL), null, "an answer from before the check");
  const english = { t: (phrase) => `<${phrase}>`, colon: ": ", comma: ", ", list: ", ", parens: (value) => ` (${value})` };
  const translated = reconcileBlock({ ...DETAIL, reconciliation: { state: "flagged", figures: 1, flagged: [{ line: "l", values: ["1", "2"] }], error: null } }, english);
  assert.equal(translated.checked, "<查过的数字>: 1");
  assert.equal(translated.note, `<${RECONCILE_NOTE}>`);
  assert.equal(translated.lines[0].values, "1, 2");
});

test("the answers tab has the 「数字没对上」 filter and the drawer shows the check's block", () => {
  const tab = src("app/backstage/AnswersTab.tsx"), drawer = src("app/backstage/AnswerDrawer.tsx");
  assert.match(tab, /data-testid="filter-reconcile" checked=\{filters\.reconcileFlagged\} onChange=\{event => set\(\{ reconcileFlagged: event\.target\.checked \}\)\}/);
  assert.match(tab, /\{t\("数字没对上"\)\}/);
  assert.match(tab, /filters\.reconcileFlagged \|\| filters\.feedbackBad \|\| searched/, "a filtered empty list says no answer matched");
  assert.match(tab, /data-testid="filter-feedback"/, "5d-3a: the 「被点不好的」 filter");
  assert.match(drawer, /const reconcile = detail \? reconcileBlock\(detail, w\) : null;/);
  assert.match(drawer, /data-testid="reconcile-note" role="note"/);
  assert.match(drawer, /data-testid="reconcile-line"/);
});

test("every phrase of the figure check is in both catalogs", () => {
  const chinese = JSON.parse(src("locales/zh-CN.json")), english = JSON.parse(src("locales/en-US.json"));
  for (const phrase of ["数字没对上", "数字对账结果", "查过的数字", "没有找不到出处的数字。", "对账没有做完", RECONCILE_NOTE]) {
    assert.ok(chinese.includes(phrase), phrase);
    assert.ok(english[phrase]?.trim(), phrase);
  }
});


// ---- 5d-2: 记忆变更 ------------------------------------------------------------------------------------------------

const CONVERSATION = "c0ffee00-0000-4000-8000-000000000001";
const CHANGE = { id: "e-1", at: "2026-11-27T10:30:00+00:00", target: "profile", action: "added", by: "chat", text: "金额用亿美元", before: null, reason: null,
  bot: null, symbol: null, company: null, reconstructed: false, quote: "以后金额用亿美元", examples: [], conversation_id: CONVERSATION, message_id: "m-1",
  run: null, template: null, from_bot: null, to_bot: null };
const change = (patch) => memoryRow({ ...CHANGE, ...patch }, "UTC");

test("the memory-changes query carries only the filters that are set, and 变更 is the actions it stands for", () => {
  assert.equal(memoryQuery(MEMORY_FILTER_DEFAULTS), "");
  assert.equal(memoryQuery({ ...MEMORY_FILTER_DEFAULTS, target: "view", change: "recorded", by: "page", q: " NVDA ", before: "1.x" }),
    "?target=view&action=added%2Crecorded&by=page&q=NVDA&before=1.x");
  assert.equal(memoryQuery({ ...MEMORY_FILTER_DEFAULTS, change: "deleted" }), "?action=deleted%2Crejected");
  assert.equal(memoryQuery({ ...MEMORY_FILTER_DEFAULTS, target: "junk", change: "junk", by: "junk" }), "", "a value the API does not know is not sent");
  assert.equal(memoryQuery({ ...MEMORY_FILTER_DEFAULTS, q: "x".repeat(150) }), `?q=${"x".repeat(100)}`);
  assert.deepEqual(MEMORY_TARGETS.map((choice) => choice.label), ["记忆", "看法"]);
  assert.deepEqual(MEMORY_CHANGES.map((choice) => choice.label), ["记下", "推测", "确认", "修改", "归档", "恢复", "删除"]);
  assert.deepEqual(MEMORY_BYS.map((choice) => choice.label), ["对话里", "记忆页", "每月整理", "季度沉淀", "角色模板", "旧流程提取"]);
  const api = ["added", "noticed", "proposed", "confirmed", "edited", "moved", "archived", "restored", "settled", "rejected", "deleted", "recorded", "superseded", "dropped"];
  assert.deepEqual([...new Set(MEMORY_CHANGES.flatMap((choice) => choice.actions))].sort(), [...api].sort(), "every action the API records has a filter, and no other");
});

test("a change said in chat: the object, the action, his words, who, his quote and the conversation it came from", () => {
  assert.deepEqual(change({}), { id: "e-1", time: "11-27 10:30", what: "记忆", action: "记下", content: "金额用亿美元", gone: false, by: "对话里",
    basis: ["「以后金额用亿美元」"], link: { label: "查看原对话", to: `/chat/c/${CONVERSATION}` }, reconstructed: "" });
  assert.equal(change({ conversation_id: null }).link, null, "no conversation, no link");
  assert.equal(change({ bot: "研究员" }).what, "记忆 · 研究员", "a bot's own memory names the bot");
});

test("an edit shows old → new; a deleted or rejected item, and an earlier change of one, keeps no words", () => {
  const edit = change({ action: "edited", by: "page", before: "金额用万元", quote: null, conversation_id: null });
  assert.deepEqual([edit.action, edit.content, edit.by, edit.basis], ["修改", "金额用万元 → 金额用亿美元", "记忆页", []]);
  for (const action of ["deleted", "rejected"]) {
    const gone = change({ action, text: null, quote: null });
    assert.equal(gone.content, MEMORY_GONE, action);
    assert.equal(gone.gone, true, action);
  }
  assert.equal(change({ action: "deleted", text: "不该出现" }).content, MEMORY_GONE, "even a text the API sent by mistake is not shown for a deletion");
  const scrubbed = change({ text: null, quote: null });
  assert.equal(scrubbed.content, MEMORY_GONE, "an earlier change of a deleted item");
  assert.deepEqual(scrubbed.basis, []);
  assert.equal(change({ action: "rejected", text: null }).action, "否掉推测");
  assert.equal(MEMORY_GONE, "（已删除，内容不保留）");
});

test("a reconstructed change says 补记, and the note under the table says what that means", () => {
  assert.equal(change({ reconstructed: true }).reconstructed, "补记");
  assert.equal(change({ reconstructed: "yes" }).reconstructed, "", "only a true flag");
  assert.equal(MEMORY_NOTE, "标「补记」的是这一栏上线前的变更，按记忆里已有的时间推出来的；那之前的修改和删除没有留下记录。");
});

test("a view names its company; each view action has its word; the settle's reason is shown as it wrote it", () => {
  const view = { target: "view", symbol: "NVDA", company: "英伟达", text: "估值太高了", quote: "估值太高了，我觉得" };
  assert.equal(change({ ...view, action: "recorded" }).what, "看法 · 英伟达（NVDA）");
  assert.equal(change({ ...view, company: "AAPL", symbol: "AAPL", action: "recorded" }).what, "看法 · AAPL", "a ticker with no Chinese name is not doubled");
  assert.deepEqual(["recorded", "superseded", "dropped", "archived", "restored", "deleted"].map((action) => change({ ...view, action }).action),
    ["记下", "被取代", "撤回", "归档", "恢复", "删除"]);
  const archived = change({ ...view, action: "archived", by: "settle", quote: null, conversation_id: null, reason: "你已不持有、不在关注列表，也很久没提" });
  assert.deepEqual([archived.by, archived.basis], ["季度沉淀", ["原因：你已不持有、不在关注列表，也很久没提"]]);
});

test("every profile action has its word; the code's reasons, the review's examples and a layer move read in words", () => {
  assert.deepEqual(["added", "noticed", "proposed", "confirmed", "edited", "moved", "archived", "restored", "settled", "rejected", "deleted"].map((action) => change({ action }).action),
    ["记下", "推测", "推测", "确认", "修改", "改范围", "归档", "恢复", "转为长期", "否掉推测", "删除"]);
  const proposed = change({ action: "proposed", by: "review", quote: null, conversation_id: null, examples: [{ quote: "a" }, { quote: "b" }, "junk"] });
  assert.deepEqual([proposed.by, proposed.basis], ["每月整理", ["例句：2"]]);
  assert.deepEqual(change({ action: "archived", quote: null, reason: "cap" }).basis, ["原因：超过 30 条上限"]);
  assert.deepEqual(change({ action: "archived", quote: null, reason: "replaced" }).basis, ["原因：同一主题有了新的一条"]);
  assert.deepEqual(change({ action: "archived", quote: null, reason: "limit" }).basis, ["原因：待确认的推测超过 20 条"]);
  assert.deepEqual(change({ action: "archived", quote: null, reason: "stale" }).basis, ["原因：60 天没有回应"]);
  assert.deepEqual(change({ action: "confirmed", quote: null, reason: "restated" }).basis, ["原因：你自己又说了一遍"]);
  const moved = change({ action: "moved", by: "page", quote: null, conversation_id: null, from_bot: { id: null, name: null }, to_bot: { id: "b-1", name: "研究员" } });
  assert.deepEqual(moved.basis, ["范围：全局 → 研究员"]);
  assert.deepEqual(change({ action: "moved", quote: null, from_bot: { id: "b-1", name: null }, to_bot: { id: null, name: null } }).basis.slice(0, 1), ["范围：已删除的 bot → 全局"]);
  assert.deepEqual(["template", "extract", "settle", "unknown", "???"].map((by) => change({ by }).by), ["角色模板", "旧流程提取", "季度沉淀", "不明", "???"]);
  const english = { t: (phrase) => `<${phrase}>`, colon: ": ", comma: ", ", list: ", ", parens: (value) => ` (${value})` };
  const translated = memoryRow({ ...CHANGE, target: "view", symbol: "NVDA", company: "英伟达", action: "archived", reason: "stale", quote: null }, "UTC", english);
  assert.deepEqual([translated.what, translated.action, translated.basis], ["<看法> · 英伟达 (NVDA)", "<归档>", ["<原因>: <60 天没有回应>"]]);
});

test("the memory tab: its filters go into the request, the note sits under the table, and it writes nothing", () => {
  const tab = src("app/backstage/MemoryTab.tsx"), page = src("app/backstage/BackstagePage.tsx"), api = src("api/backstage.ts");
  for (const id of ["filter-target", "filter-change", "filter-by", "filter-q"]) assert.match(tab, new RegExp(`data-testid="${id}"`), id);
  assert.match(tab, /listMemoryChanges\(applied, before, signal\)/, "the filters (with the settled search) are what is asked for");
  assert.match(tab, /const key = JSON\.stringify\(applied\);/, "a new filter starts the list again");
  assert.match(tab, /\{t\(MEMORY_NOTE\)\}/);
  assert.match(tab, /<Link to=\{row\.link\.to\}/, "the conversation opens in the app");
  assert.match(api, /get<Paged<MemoryChangeItem>>\(`memory\$\{memoryQuery\(\{ \.\.\.filters, before: before \?\? "" \}\)\}`, signal\)/);
  assert.match(page, /\{ value: "memory", testId: "tab-memory", label: t\("记忆变更"\) \}/);
  assert.match(page, /\{tab === "memory" && <MemoryTab \/>\}/);
  assert.doesNotMatch(tab, /method:\s*"(POST|PUT|PATCH|DELETE)"|<form|type="submit"/);
  assert.deepEqual(api.match(/method:\s*"(POST|PUT|PATCH|DELETE)"/g), ['method: "POST"'], "still only the feedback POST");
});

test("every phrase of the memory-changes tab is in both catalogs", () => {
  const chinese = JSON.parse(src("locales/zh-CN.json")), english = JSON.parse(src("locales/en-US.json"));
  const phrases = [...MEMORY_TARGETS, ...MEMORY_CHANGES, ...MEMORY_BYS].map((choice) => choice.label).concat([
    MEMORY_NOTE, MEMORY_GONE, "记忆变更", "对象", "变更", "谁改的", "内容", "依据", "全部", "筛选记忆变更", "搜索内容和原因", "没有符合筛选的变更。", "还没有记忆变更的记录。",
    "记下、修改、归档或删除一条记忆或看法时，这里就多一行。", "记忆变更记录", "改范围", "转为长期", "否掉推测", "被取代", "撤回", "不明", "同一主题有了新的一条", "超过 30 条上限",
    "待确认的推测超过 20 条", "60 天没有回应", "你自己又说了一遍", "例句", "原因", "范围", "全局", "已删除的 bot", "查看原对话", "补记"]);
  for (const phrase of phrases) {
    assert.ok(chinese.includes(phrase), phrase);
    assert.ok(english[phrase]?.trim(), phrase);
  }
});

test("a memory item whose bot was deleted reads 记忆 · 已删除的 bot, not the global layer, with its reason in words", () => {
  const row = change({ action: "archived", bot: null, bot_deleted: true, reason: "bot_deleted", quote: null });
  assert.equal(row.what, "记忆 · 已删除的 bot");
  assert.ok(row.basis.includes("原因：所属的 bot 被删除"), row.basis.join(" | "));
  assert.equal(change({ bot: null, bot_deleted: false }).what, "记忆");
});


test("5d-3a: 「被点不好的」 is feedback=bad; a row says his verdict; the detail shows it and his reason", () => {
  assert.equal(answersQuery({ ...ANSWER_FILTER_DEFAULTS, feedbackBad: true }), "?feedback=bad");
  assert.equal(answersQuery(ANSWER_FILTER_DEFAULTS), "");
  assert.equal(answerRow({ message_id: "m1", feedback: "bad" }, "UTC").feedback, "你点了不好");
  assert.equal(answerRow({ message_id: "m1", feedback: "good" }, "UTC").feedback, "你点了好");
  assert.equal(answerRow({ message_id: "m1", feedback: null }, "UTC").feedback, "");
  assert.deepEqual(answerFeedbackBlock({ feedback: { verdict: "bad", reason: "数据太旧了" } }), { verdict: "bad", text: "你点了不好", reason: "原因：数据太旧了" });
  assert.deepEqual(answerFeedbackBlock({ feedback: { verdict: "good", reason: "x" } }), { verdict: "good", text: "你点了好", reason: "" });
  assert.equal(answerFeedbackBlock({ feedback: null }), null);
  assert.equal(answerFeedbackBlock({}), null);
});


test("5d-3b 质量: a week, an answer marked 不好, a ruler run with and without its record", () => {
  assert.deepEqual(qualityWeekRow({ week_start: "2026-11-23", good: 3, bad: 1 }), { id: "2026-11-23", week: "11-23 那周", good: "3", bad: "1" });
  const english = { t: (phrase) => ({ "{date} 那周": "Week of {date}" })[phrase] ?? phrase, colon: ": ", comma: ", ", list: ", ", parens: (value) => ` (${value})` };
  assert.equal(qualityWeekRow({ week_start: "2026-11-23" }, english).week, "Week of 11-23");
  assert.deepEqual(qualityWeekRow({}), { id: "", week: "—", good: "0", bad: "0" });
  const bad = badAnswerRow({ message_id: "m1", at: "2026-11-27T12:46:00+00:00", bot: "研究员", question: "英伟达营收", reason: "没说环比", channel: "chat" }, "UTC");
  assert.deepEqual(bad, { id: "m1", time: "11-27 12:46", bot: "研究员", question: "英伟达营收", reason: "没说环比", said: "在对话里说的" });
  assert.equal(badAnswerRow({ message_id: "m2", reason: null, channel: "web" }, "UTC").reason, "（没写原因）");
  const run = rulerRunRow({ name: "5d3a2-20261127", at: "2026-11-27T12:58:00+00:00", meta: true, note: "65fc373", turns: 86, pass_rate: 0.9883720930232558,
    total_ms_p50: 6077, total_ms_p90: 12072, failed: [{ case_id: "B06", turn: 0, checks: ["include_any[0]"] }] }, "UTC");
  assert.deepEqual(run, { id: "5d3a2-20261127", time: "11-27 12:58", name: "5d3a2-20261127", note: "65fc373", turns: "86", pass_rate: "98.8%", p50: "6.1 s", p90: "12.1 s",
    failed: "B06", all_passed: false });
  const early = rulerRunRow({ name: "baseline-v1", meta: false, turns: 86, pass_rate: 1, failed: [] }, "UTC");
  assert.equal(early.note, EARLY_RUN);
  assert.equal(early.failed, "全过");
  assert.equal(early.pass_rate, "100.0%");
  assert.equal(rulerRunRow({ name: "x", pass_rate: null, turns: null }, "UTC").pass_rate, "—");
});
